from __future__ import annotations

from adc_core.models import FileCoverage, Finding

from adc_api.corpus import CorpusFile

_SEV_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


class SelectionError(ValueError):
    """Raised when the marked set exceeds the hard ceiling."""


def _max_sev_by_file(scanner_findings: list[Finding]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in scanner_findings:
        path = f.location.file
        if path is None:
            continue
        out[path] = max(out.get(path, 0), _SEV_RANK.get(f.severity, 0))
    return out


def select_agent_files(
    files: list[CorpusFile], *, marked: set[str], scanner_findings: list[Finding],
    cap: int, ceiling: int,
) -> tuple[list[str], list[FileCoverage]]:
    """Return (agent_set_paths, per-file coverage).

    Priority: marked files (always kept, even past `cap`, up to `ceiling`), then scanner-hit
    files by descending severity until `cap`. If nothing is marked or flagged, fall back to the
    first `cap` source files so the agents always contribute.
    """
    all_paths = [f.path for f in files]
    marked = {m for m in marked if m in set(all_paths)}
    if len(marked) > ceiling:
        raise SelectionError(
            f"{len(marked)} files marked for deep review; max is {ceiling}. Narrow your selection."
        )

    hits = _max_sev_by_file(scanner_findings)
    hit_paths = sorted(
        (p for p in all_paths if p in hits and p not in marked),
        key=lambda p: (-hits[p], all_paths.index(p)),
    )

    chosen: dict[str, str] = {p: "marked" for p in marked}
    remaining = max(cap - len(chosen), 0)
    for p in hit_paths[:remaining]:
        chosen[p] = "scanner-hit"

    if not chosen:  # nothing marked, nothing flagged -> review the first N source files
        for f in files:
            if f.language is not None and len(chosen) < cap:
                chosen[f.path] = "fallback"

    coverage: list[FileCoverage] = []
    for p in all_paths:
        if p in chosen:
            coverage.append(FileCoverage(path=p, agent_reviewed=True, reason=chosen[p]))
        elif p in hits:
            coverage.append(FileCoverage(path=p, agent_reviewed=False, reason="over-cap"))
        else:
            coverage.append(FileCoverage(path=p, agent_reviewed=False, reason="not-flagged"))
    return list(chosen), coverage
