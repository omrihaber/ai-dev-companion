from __future__ import annotations

from adc_core.models import Finding, Location, Severity, Source

_SEV_RANK: dict[Severity, int] = {
    "critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1,
}


def _overlap(a: Location, b: Location) -> bool:
    return a.start_line <= b.end_line and b.start_line <= a.end_line


def _merge_sources(a: list[Source], b: list[Source]) -> list[Source]:
    by_name: dict[str, Source] = {s.name: s for s in a}
    for s in b:
        by_name.setdefault(s.name, s)
    return list(by_name.values())


def aggregate(findings: list[Finding]) -> list[Finding]:
    """Dedupe by (category, overlapping line range), union sources, keep max severity,
    keep the most-specific text, then rank by severity desc, then start line asc.

    The seam Inc 5 reuses: external-scanner findings merge into existing findings as extra
    citations. `syntax` findings never merge into other categories.
    """
    merged: list[Finding] = []
    for f in findings:
        hit = None
        for m in merged:
            if m.category == f.category and _overlap(m.location, f.location):
                hit = m
                break
        if hit is None:
            merged.append(f.model_copy(deep=True))
            continue
        hit.sources = _merge_sources(hit.sources, f.sources)
        if _SEV_RANK[f.severity] > _SEV_RANK[hit.severity]:
            hit.severity = f.severity
        if len(f.description) > len(hit.description):
            hit.title = f.title
            hit.description = f.description
            hit.recommendation = f.recommendation
        hit.location = Location(
            file=hit.location.file,
            start_line=min(hit.location.start_line, f.location.start_line),
            end_line=max(hit.location.end_line, f.location.end_line),
        )

    merged.sort(key=lambda x: (-_SEV_RANK[x.severity], x.location.start_line))
    return merged
