import pytest
from adc_api.providers import MockProvider
from adc_api.review_service import ReviewService


@pytest.mark.asyncio
async def test_run_merges_syntax_and_agent_findings_and_emits_progress():
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "concat", "recommendation": "params", "start_line": 2, "end_line": 2,
    }])
    stages: list[str] = []
    svc = ReviewService(provider=provider)
    result = await svc.run(
        review_id="r1", language="python",
        code="def f(uid):\n    q = 'SELECT ' + uid\n",
        on_progress=lambda e: stages.append(e.stage),
    )
    assert result.status == "done"
    cats = {f.category for f in result.findings}
    assert "security" in cats
    assert result.findings[0].sources  # citation present
    assert "analyzing" in stages and "done" in stages

@pytest.mark.asyncio
async def test_run_marks_failed_on_provider_error():
    class Boom(MockProvider):
        async def review(self, code, language):
            raise RuntimeError("model down")
    svc = ReviewService(provider=Boom())
    result = await svc.run(
        review_id="r2", language="python", code="x=1\n", on_progress=lambda e: None
    )
    assert result.status == "failed"
    assert "model down" in (result.error or "")
