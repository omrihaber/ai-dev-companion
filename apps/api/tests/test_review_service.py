import pytest
from adc_api.agents import build_agents
from adc_api.providers import MockProvider
from adc_api.review_service import ReviewService


@pytest.mark.asyncio
async def test_all_agents_run_and_identical_findings_merge_with_per_agent_progress():
    # Shared mock: every agent returns the SAME seeded issue (same title + line). The aggregator
    # merges them across categories into ONE card citing all six agents — and per-agent progress
    # still reaches "done" for each, proving the fan-out ran.
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQL injection",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }]))
    events: list[tuple[str, dict]] = []
    svc = ReviewService(agents=agents)
    result = await svc.run(
        review_id="r1", language="python", code="x = 1\n",
        on_progress=lambda e: events.append((e.stage, e.sub_status)),
    )
    assert result.status == "done"
    # all six agents flagged the same issue -> merged into one card citing all six sources
    assert len(result.findings) == 1
    assert {s.name for s in result.findings[0].sources} == {
        "security-agent", "performance-agent", "logic-agent",
        "quality-agent", "docs-agent", "tests-agent",
    }
    stages = [s for s, _ in events]
    assert "analyzing" in stages and "done" in stages
    final_sub = [sub for s, sub in events if s == "analyzing"][-1]
    assert all(v == "done" for v in final_sub.values())


@pytest.mark.asyncio
async def test_all_agents_failing_surfaces_as_failed_not_clean():
    # If every agent errors (e.g. bad API key), the review must NOT look like a clean "done".
    class _Boom(MockProvider):
        async def complete_structured(self, **kwargs):
            raise RuntimeError("auth error")

    svc = ReviewService(agents=build_agents(provider=_Boom()), scanners=[])
    stages: list[str] = []
    result = await svc.run(
        review_id="rf", language="python", code="x = 1\n",
        on_progress=lambda e: stages.append(e.stage),
    )
    assert result.status == "failed"
    assert "agents failed" in (result.error or "")
    assert stages[-1] == "failed"
