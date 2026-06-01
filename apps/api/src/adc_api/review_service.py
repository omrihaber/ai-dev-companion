from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from adc_core.models import Coverage, Finding, ReviewResult, ReviewStatus
from adc_core.syntax import check_syntax

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.aggregator import aggregate
from adc_api.corpus import CorpusFile
from adc_api.graph import build_graph
from adc_api.scanners import Scanner, build_scanners
from adc_api.schemas import ProgressEvent
from adc_api.selection import select_agent_files
from adc_api.settings import settings

OnProgress = Callable[[ProgressEvent], None]


def _summarize(findings: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.category] = counts.get(f.category, 0) + 1
    return ", ".join(f"{n} {c}" for c, n in sorted(counts.items())) or "no issues found"


class ReviewService:
    """Runs the two-tier corpus review behind a stable run() signature."""

    def __init__(
        self,
        agents: list[SpecialistAgent] | None = None,
        scanners: list[Scanner] | None = None,
    ) -> None:
        self._agents = agents if agents is not None else build_agents()
        self._scanners = scanners if scanners is not None else build_scanners()
        self._agent_names = {a.name for a in self._agents}
        self._graph = build_graph(self._agents)  # agents-only per-file fan-out

    async def _scan_corpus(self, work_dir: str, languages: set[str]) -> list[Finding]:
        async def run_one(scanner: Scanner) -> list[Finding]:
            if scanner.languages and not (scanner.languages & languages):
                return []
            try:
                return await scanner.scan_path(work_dir)
            except Exception:  # noqa: BLE001 — a scanner failure never sinks the review
                return []

        results = await asyncio.gather(*(run_one(s) for s in self._scanners))
        return [f for r in results for f in r]

    async def _review_file(
        self, f: CorpusFile, work_dir: str
    ) -> tuple[list[Finding], set[str], bool]:
        """Run the agent fan-out on one file. Returns (findings, failed_agents, any_agent_ok)."""
        syntax = check_syntax(f.language or "", f.content) if f.language else []
        for s in syntax:
            s.location.file = f.path
        findings: list[Finding] = list(syntax)
        failed: set[str] = set()
        any_ok = False
        async for update in self._graph.astream(
            {"code": f.content, "language": f.language or "text", "file": f.path,
             "work_dir": work_dir, "findings": list(syntax), "failures": [], "result": []},
            stream_mode="updates",
        ):
            for node_name, delta in update.items():
                if node_name in self._agent_names:
                    if isinstance(delta, dict) and delta.get("failures"):
                        failed.update(delta["failures"])
                    else:
                        any_ok = True
                if isinstance(delta, dict) and node_name == "aggregate":
                    findings = delta["result"]
        return findings, failed, any_ok

    async def run(
        self, *, review_id: str, files: list[CorpusFile], marked: set[str],
        on_progress: OnProgress, work_dir: str | None = None,
        parent_review_id: str | None = None,
    ) -> ReviewResult:
        started = time.monotonic()
        model_label = ",".join(sorted({a.provider.model for a in self._agents}))
        result = ReviewResult(
            id=review_id, language=(files[0].language or "text") if files else "text",
            model=model_label, parent_review_id=parent_review_id,
        )

        def emit(stage: ReviewStatus, **kw) -> None:
            result.status = stage
            on_progress(ProgressEvent(review_id=review_id, stage=stage, **kw))

        try:
            emit("validating")
            languages = {f.language for f in files if f.language}

            def sub(scan: str, reviewed: int, total: int) -> dict[str, str]:
                return {"scan": scan, "filesReviewed": str(reviewed), "filesTotal": str(total)}

            emit("analyzing", sub_status=sub("running", 0, 0))
            scanner_findings = (
                await self._scan_corpus(work_dir, languages)
                if work_dir and self._scanners else []
            )

            agent_paths, coverage_files = select_agent_files(
                files, marked=marked, scanner_findings=scanner_findings,
                cap=settings.agent_file_cap, ceiling=settings.agent_file_ceiling,
            )
            agent_set = [f for f in files if f.path in set(agent_paths)]
            total = len(agent_set)
            emit("analyzing", sub_status=sub("done", 0, total))

            sem = asyncio.Semaphore(settings.file_concurrency)
            reviewed = 0
            all_findings: list[Finding] = list(scanner_findings)
            failed_agents: set[str] = set()
            any_agent_ok = False

            async def worker(cf: CorpusFile) -> None:
                nonlocal reviewed, any_agent_ok
                async with sem:
                    f_findings, f_failed, f_ok = await self._review_file(cf, work_dir or "")
                all_findings.extend(f_findings)
                failed_agents.update(f_failed)
                any_agent_ok = any_agent_ok or f_ok
                reviewed += 1
                emit("analyzing", sub_status=sub("done", reviewed, total))

            await asyncio.gather(*(worker(cf) for cf in agent_set))

            aggregated = aggregate(all_findings)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            result.coverage = Coverage(
                files_total=len(files),
                files_agent_reviewed=sum(1 for c in coverage_files if c.agent_reviewed),
                files=coverage_files,
            )

            if agent_set and not any_agent_ok and failed_agents and not [
                f for f in aggregated if any(s.type == "agent" for s in f.sources)
            ]:
                result.error = (
                    f"All review agents failed ({', '.join(sorted(failed_agents))}). "
                    "Check the model provider / API key."
                )
                emit("failed", message=result.error)
            else:
                emit("finalizing")
                result.findings = aggregated
                result.summary = _summarize(aggregated)
                emit("done")
        except Exception as exc:  # noqa: BLE001 — surfaced to the user as a failed job
            result.error = str(exc)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            emit("failed", message=str(exc))
        return result
