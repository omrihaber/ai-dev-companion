import pytest
from adc_api.corpus import CorpusFile
from adc_api.selection import SelectionError, select_agent_files
from adc_core.models import Finding, Location, Source


def _files(*paths):
    return [CorpusFile(p, "x=1\n", "python") for p in paths]


def _hit(file, severity="high"):
    return Finding(
        id=file, category="security", severity=severity, title="t", description="d",
        recommendation="r", location=Location(file=file, start_line=1, end_line=1),
        sources=[Source(type="tool", name="bandit")],
    )


def test_marked_and_scanner_hits_are_reviewed():
    files = _files("a.py", "b.py", "c.py")
    paths, coverage = select_agent_files(
        files, marked={"a.py"}, scanner_findings=[_hit("b.py")], cap=25, ceiling=150,
    )
    assert set(paths) == {"a.py", "b.py"}
    by = {c.path: c for c in coverage}
    assert by["a.py"].reason == "marked" and by["a.py"].agent_reviewed
    assert by["b.py"].reason == "scanner-hit" and by["b.py"].agent_reviewed
    assert by["c.py"].reason == "not-flagged" and not by["c.py"].agent_reviewed


def test_cap_limits_scanner_hits_by_severity_marks_always_kept():
    files = _files("m.py", "lo.py", "hi.py")
    paths, coverage = select_agent_files(
        files, marked={"m.py"},
        scanner_findings=[_hit("lo.py", "low"), _hit("hi.py", "critical")],
        cap=2, ceiling=150,
    )
    assert set(paths) == {"m.py", "hi.py"}
    by = {c.path: c for c in coverage}
    assert by["lo.py"].reason == "over-cap" and not by["lo.py"].agent_reviewed


def test_marks_override_cap_up_to_ceiling():
    files = _files("a.py", "b.py", "c.py")
    paths, _ = select_agent_files(
        files, marked={"a.py", "b.py", "c.py"}, scanner_findings=[], cap=1, ceiling=150,
    )
    assert set(paths) == {"a.py", "b.py", "c.py"}


def test_marks_over_ceiling_rejected():
    files = _files("a.py", "b.py", "c.py")
    with pytest.raises(SelectionError):
        select_agent_files(files, marked={"a.py", "b.py", "c.py"}, scanner_findings=[],
                           cap=25, ceiling=2)


def test_empty_selection_falls_back_to_first_n_source_files():
    files = _files("a.py", "b.py", "c.py")
    paths, coverage = select_agent_files(
        files, marked=set(), scanner_findings=[], cap=2, ceiling=150,
    )
    assert len(paths) == 2
    assert all(c.reason == "fallback" for c in coverage if c.agent_reviewed)
