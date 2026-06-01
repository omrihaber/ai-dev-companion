from __future__ import annotations

import re

from adc_core.models import Finding, Location, Severity, Source

_SEV_RANK: dict[Severity, int] = {
    "critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1,
}
# Lower index = higher priority when choosing the representative category for a merged finding.
_CATEGORY_PRIORITY = ["security", "logic", "performance", "quality", "docs", "tests", "syntax"]
_TITLE_SIMILARITY_THRESHOLD = 0.6


def _overlap(a: Location, b: Location) -> bool:
    return a.start_line <= b.end_line and b.start_line <= a.end_line


def _title_tokens(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", title.lower()))


def _similar_title(a: str, b: str) -> bool:
    """Token-containment similarity: |A∩B| / min(|A|,|B|). Robust to one title being a
    longer phrasing of the other (e.g. 'SQL Injection' vs 'Untested SQL Injection')."""
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= _TITLE_SIMILARITY_THRESHOLD


def _priority(category: str) -> int:
    if category in _CATEGORY_PRIORITY:
        return _CATEGORY_PRIORITY.index(category)
    return len(_CATEGORY_PRIORITY)


def _mergeable(head: Finding, f: Finding) -> bool:
    # `syntax` findings (deterministic parse errors) never merge with agent findings.
    if head.category == "syntax" or f.category == "syntax":
        return False
    if head.location.file != f.location.file:   # findings only merge within the same file
        return False
    return _overlap(head.location, f.location) and _similar_title(head.title, f.title)


def aggregate(findings: list[Finding]) -> list[Finding]:
    """Cluster findings that describe the same issue — overlapping line range AND similar
    title, ACROSS categories — into one finding that cites every source. The representative
    is the highest-severity member (ties broken by category priority); sources are unioned and
    the location widened. Result is ranked by severity desc, then start line asc.

    `syntax` findings always pass through unmerged. This is the seam Inc 5 reuses: external
    scanner findings (Semgrep/SonarQube) merge into the matching agent finding as extra citations.
    """
    clusters: list[list[Finding]] = []
    for f in findings:
        for cluster in clusters:
            if _mergeable(cluster[0], f):
                cluster.append(f)
                break
        else:
            clusters.append([f])

    out: list[Finding] = []
    for cluster in clusters:
        rep = min(cluster, key=lambda x: (-_SEV_RANK[x.severity], _priority(x.category)))
        merged = rep.model_copy(deep=True)
        seen: dict[str, Source] = {}
        for member in cluster:
            for s in member.sources:
                seen.setdefault(s.name, s)
        merged.sources = list(seen.values())
        merged.location = Location(
            file=rep.location.file,
            start_line=min(m.location.start_line for m in cluster),
            end_line=max(m.location.end_line for m in cluster),
        )
        out.append(merged)

    out.sort(key=lambda x: (-_SEV_RANK[x.severity], x.location.start_line))
    return out
