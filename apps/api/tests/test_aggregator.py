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


def test_merges_across_categories_when_titles_similar():
    # The same SQL-injection issue flagged by 4 agents under different categories -> ONE card.
    out = aggregate([
        _f("security", "high", "security-agent", 2, 2, title="SQL Injection"),
        _f("logic", "high", "logic-agent", 2, 2, title="SQL Injection Vulnerability"),
        _f("quality", "medium", "quality-agent", 2, 2,
           title="Untested SQL Injection Vulnerability"),
        _f("tests", "low", "tests-agent", 2, 2, title="SQL Injection not covered by tests"),
    ])
    assert len(out) == 1
    assert out[0].category == "security"  # highest severity, security wins the priority tie
    assert {s.name for s in out[0].sources} == {
        "security-agent", "logic-agent", "quality-agent", "tests-agent",
    }


def test_does_not_merge_across_categories_when_titles_differ():
    # Two genuinely different issues on the same line stay as separate cards.
    out = aggregate([
        _f("security", "high", "security-agent", 2, 2, title="SQL Injection"),
        _f("performance", "high", "perf-agent", 2, 2, title="Inefficient loop allocation"),
    ])
    assert len(out) == 2


def test_same_issue_in_two_files_does_not_merge():
    from adc_api.aggregator import aggregate
    from adc_core.models import Finding, Location, Source

    def mk(file):
        return Finding(
            id=file, category="security", severity="high", title="SQL injection",
            description="d", recommendation="r",
            location=Location(file=file, start_line=2, end_line=2),
            sources=[Source(type="agent", name="security-agent")],
        )

    out = aggregate([mk("auth.py"), mk("db.py")])
    assert len(out) == 2
    assert {f.location.file for f in out} == {"auth.py", "db.py"}


def test_same_file_two_sources_merge_into_one_card():
    from adc_api.aggregator import aggregate
    from adc_core.models import Finding, Location, Source

    agent = Finding(
        id="a", category="security", severity="high", title="SQL injection",
        description="d", recommendation="r",
        location=Location(file="auth.py", start_line=2, end_line=2),
        sources=[Source(type="agent", name="security-agent")],
    )
    tool = Finding(
        id="b", category="security", severity="high", title="SQL injection vector",
        description="d", recommendation="r",
        location=Location(file="auth.py", start_line=2, end_line=2),
        sources=[Source(type="tool", name="bandit")],
    )
    out = aggregate([agent, tool])
    assert len(out) == 1
    assert {s.name for s in out[0].sources} == {"security-agent", "bandit"}
