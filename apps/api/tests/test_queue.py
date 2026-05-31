import pytest
from adc_api.agents import build_agents
from adc_api.events import InMemoryEventBus
from adc_api.providers import MockProvider
from adc_api.queue import InlineReviewQueue
from adc_api.repository import InMemoryReviewRepository


@pytest.mark.asyncio
async def test_inline_queue_runs_review_immediately():
    repo = InMemoryReviewRepository()
    bus = InMemoryEventBus()
    await repo.create("r1", "python")
    q = InlineReviewQueue(
        repo,
        bus,
        agents_factory=lambda: build_agents(provider=MockProvider(seed=[{
            "category": "security", "severity": "high", "title": "SQLi",
            "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
        }])),
    )
    await q.enqueue("r1", "python", "x = 1\n")
    final = await repo.get("r1")
    assert final.status == "done" and len(final.findings) == 1
