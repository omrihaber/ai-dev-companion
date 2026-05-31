from adc_core.models import Finding, Location, Source, ReviewResult

def test_finding_serializes_to_camelcase_with_sources():
    f = Finding(
        id="f1", category="security", severity="high",
        title="SQL injection", description="String concat in query",
        recommendation="Use parameterized queries",
        location=Location(start_line=2, end_line=2),
        sources=[Source(type="agent", name="core-reviewer")],
    )
    data = f.model_dump(by_alias=True)
    assert data["location"]["startLine"] == 2
    assert data["sources"][0]["name"] == "core-reviewer"

def test_review_result_defaults_status_and_findings():
    r = ReviewResult(id="r1", language="python", model="mock")
    assert r.status == "queued"
    assert r.findings == []
