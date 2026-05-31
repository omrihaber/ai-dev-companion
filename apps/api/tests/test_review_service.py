import pytest
from adc_api.agents import build_agents
from adc_api.providers import MockProvider
from adc_api.review_service import ReviewService


@pytest.mark.asyncio
async def test_run_produces_multi_category_findings_and_per_agent_progress():
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "issue",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }]))
    events: list[tuple[str, dict]] = []
    svc = ReviewService(agents=agents)
    result = await svc.run(
        review_id="r1", language="python", code="x = 1\n",
        on_progress=lambda e: events.append((e.stage, e.sub_status)),
    )
    assert result.status == "done"
    cats = {f.category for f in result.findings}
    assert {"security", "performance", "logic", "quality", "docs", "tests"} <= cats
    stages = [s for s, _ in events]
    assert "analyzing" in stages and "done" in stages
    final_sub = [sub for s, sub in events if s == "analyzing"][-1]
    assert all(v == "done" for v in final_sub.values())
