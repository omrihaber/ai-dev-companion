import asyncio

import pytest
from adc_api.agents import build_agents
from adc_api.events import InMemoryEventBus
from adc_api.providers import MockProvider
from adc_api.repository import InMemoryReviewRepository
from adc_api.worker import run_review_core


@pytest.mark.asyncio
async def test_run_review_core_persists_final_and_publishes_progress():
    repo = InMemoryReviewRepository()
    bus = InMemoryEventBus()
    await repo.create("r1", "python")
    agen = await bus.subscribe("r1")  # subscribe before the run so we see live events
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
    }]))
    task = asyncio.create_task(
        run_review_core("r1", "python", "x = 1\n", repo=repo, bus=bus, agents=agents)
    )
    stages = [ev.stage async for ev in agen]
    await task
    assert "analyzing" in stages and stages[-1] == "done"   # terminal published after save
    final = await repo.get("r1")
    assert final.status == "done" and len(final.findings) == 1  # 6 agents -> merged into one card
