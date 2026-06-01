from __future__ import annotations

import time
from collections.abc import Callable

from adc_core.models import Finding, ReviewResult, ReviewStatus
from adc_core.syntax import check_syntax

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.graph import build_graph
from adc_api.scanners import Scanner, build_scanners
from adc_api.schemas import ProgressEvent

OnProgress = Callable[[ProgressEvent], None]


def _summarize(findings: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.category] = counts.get(f.category, 0) + 1
    return ", ".join(f"{n} {c}" for c, n in sorted(counts.items())) or "no issues found"


class ReviewService:
    """Runs the multi-agent LangGraph review behind a stable run() signature."""

    def __init__(
        self,
        agents: list[SpecialistAgent] | None = None,
        scanners: list[Scanner] | None = None,
    ) -> None:
        self._agents = agents if agents is not None else build_agents()
        self._scanners = scanners if scanners is not None else build_scanners()
        self._agent_names = {a.name for a in self._agents}
        self._node_names = self._agent_names | {s.name for s in self._scanners}
        self._graph = build_graph(self._agents, self._scanners)

    async def run(
        self, *, review_id: str, language: str, code: str, on_progress: OnProgress
    ) -> ReviewResult:
        started = time.monotonic()
        model_label = ",".join(sorted({a.provider.model for a in self._agents}))
        result = ReviewResult(id=review_id, language=language, model=model_label)

        def emit(stage: ReviewStatus, **kw) -> None:
            result.status = stage
            on_progress(ProgressEvent(review_id=review_id, stage=stage, **kw))

        try:
            emit("validating")
            syntax = check_syntax(language, code)

            sub = {name: "running" for name in self._node_names}
            emit("analyzing", sub_status=dict(sub))

            aggregated: list[Finding] = []
            failed_nodes: set[str] = set()
            async for update in self._graph.astream(
                {"code": code, "language": language, "findings": syntax,
                 "failures": [], "result": []},
                stream_mode="updates",
            ):
                for node_name, delta in update.items():
                    if node_name in sub:
                        sub[node_name] = "done"
                        emit("analyzing", sub_status=dict(sub))
                    if isinstance(delta, dict):
                        failed_nodes.update(delta.get("failures", []))
                        if node_name == "aggregate":
                            aggregated = delta["result"]

            result.duration_ms = int((time.monotonic() - started) * 1000)
            # If EVERY agent failed (e.g. bad API key / model down) the review isn't "clean" —
            # surface it as failed instead of a misleading empty "done".
            if not aggregated and self._agent_names and self._agent_names <= failed_nodes:
                result.error = (
                    f"All {len(self._agent_names)} review agents failed "
                    f"({', '.join(sorted(self._agent_names & failed_nodes))}). "
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
