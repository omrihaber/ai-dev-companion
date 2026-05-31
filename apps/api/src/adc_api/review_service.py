from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from adc_core.models import Finding, Location, ReviewResult, ReviewStatus, Source
from adc_core.syntax import check_syntax

from adc_api.providers import ModelProvider
from adc_api.schemas import ProgressEvent, RawFinding

OnProgress = Callable[[ProgressEvent], None]


def _to_finding(raw: RawFinding, provider_name: str) -> Finding:
    return Finding(
        id=str(uuid.uuid4()),
        category=raw.category,
        severity=raw.severity,
        title=raw.title,
        description=raw.description,
        recommendation=raw.recommendation,
        location=Location(start_line=raw.start_line, end_line=raw.end_line),
        sources=[Source(type="agent", name=provider_name)],
    )


def _summarize(findings: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.category] = counts.get(f.category, 0) + 1
    return ", ".join(f"{n} {c}" for c, n in sorted(counts.items())) or "no issues found"


class ReviewService:
    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def run(
        self,
        *,
        review_id: str,
        language: str,
        code: str,
        on_progress: OnProgress,
    ) -> ReviewResult:
        started = time.monotonic()
        result = ReviewResult(id=review_id, language=language, model=self._provider.model)

        def emit(stage: ReviewStatus, **kw: object) -> None:
            result.status = stage
            on_progress(ProgressEvent(review_id=review_id, stage=stage, **kw))

        try:
            emit("validating")
            findings = check_syntax(language, code)

            emit("analyzing", sub_status={"core-reviewer": "running"})
            raw = await self._provider.review(code, language)
            findings += [_to_finding(r, self._provider.name) for r in raw]

            # NOTE: the "enriching" stage (external SARIF scanners) is part of the
            # ReviewStatus contract and shown in the UI stepper, but is intentionally
            # skipped in Inc 1 — it is emitted once the scanner fan-out lands in Inc 5.
            emit("finalizing")
            result.findings = findings
            result.summary = _summarize(findings)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            emit("done")
        except Exception as exc:  # noqa: BLE001 — surfaced to the user as a failed job
            result.error = str(exc)
            result.duration_ms = int((time.monotonic() - started) * 1000)
            emit("failed", message=str(exc))
        return result
