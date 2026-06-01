import pytest
from adc_core.models import Finding, Location, ReviewResult, Source
from pydantic import ValidationError


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


def test_finding_roundtrips_from_camelcase_payload():
    payload = {
        "id": "f1", "category": "logic", "severity": "medium",
        "title": "t", "description": "d", "recommendation": "r",
        "location": {"startLine": 3, "endLine": 4},
        "sources": [{"type": "tool", "name": "semgrep", "ruleId": "py.x"}],
    }
    f = Finding.model_validate(payload)
    assert f.location.start_line == 3
    assert f.sources[0].rule_id == "py.x"


def test_rejects_invalid_category():
    with pytest.raises(ValidationError):
        Finding(
            id="f1", category="not-a-category", severity="low",
            title="t", description="d", recommendation="r",
            location=Location(start_line=1, end_line=1),
        )


def test_category_supports_new_specialist_categories():
    for cat in ("quality", "docs", "tests"):
        f = Finding(
            id="x", category=cat, severity="low", title="t", description="d",
            recommendation="r", location=Location(start_line=1, end_line=1),
        )
        assert f.category == cat


def test_category_rejects_removed_style_value():
    with pytest.raises(ValidationError):
        Finding(
            id="x", category="style", severity="low", title="t", description="d",
            recommendation="r", location=Location(start_line=1, end_line=1),
        )


def test_review_status_no_longer_allows_enriching():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewResult(id="r1", language="python", model="m", status="enriching")
