from adc_api.aggregator import aggregate
from adc_core.models import Finding, Location, Source


def _f(cat, sev, name, s, e, title="t"):
    return Finding(
        id=name + str(s), category=cat, severity=sev, title=title, description="d",
        recommendation="r", location=Location(start_line=s, end_line=e),
        sources=[Source(type="agent", name=name)],
    )


def test_merges_same_category_overlapping_lines_and_unions_sources():
    merged = aggregate([
        _f("security", "high", "security-agent", 2, 2),
        _f("security", "critical", "semgrep", 2, 3),
    ])
    assert len(merged) == 1
    names = {s.name for s in merged[0].sources}
    assert names == {"security-agent", "semgrep"}
    assert merged[0].severity == "critical"  # max severity wins


def test_keeps_distinct_categories_and_ranks_by_severity():
    out = aggregate([
        _f("quality", "low", "quality-agent", 1, 1),
        _f("security", "critical", "security-agent", 5, 5),
    ])
    assert [f.category for f in out] == ["security", "quality"]  # critical ranked first


def test_syntax_passthrough_not_merged_into_agent_categories():
    out = aggregate([
        _f("syntax", "high", "tree-sitter", 2, 2),
        _f("security", "high", "security-agent", 2, 2),
    ])
    assert len(out) == 2
