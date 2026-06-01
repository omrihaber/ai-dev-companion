import pytest
from adc_api.agents import build_agents
from adc_api.corpus import CorpusStore, ingest_files
from adc_api.events import InMemoryEventBus
from adc_api.providers import MockProvider
from adc_api.queue import InlineReviewQueue
from adc_api.repository import InMemoryReviewRepository


@pytest.mark.asyncio
async def test_inline_queue_runs_review_as_background_task(tmp_path):
    store = CorpusStore(str(tmp_path))
    store.write("r1", ingest_files([{"path": "a.py", "content": "x = 1\n"}]))
    repo = InMemoryReviewRepository()
    await repo.create("r1", "python")
    bus = InMemoryEventBus()
    q = InlineReviewQueue(
        repo,
        bus,
        store,
        agents_factory=lambda: build_agents(provider=MockProvider(seed=[{
            "category": "security", "severity": "high", "title": "SQLi",
            "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
        }])),
    )
    agen = await bus.subscribe("r1")          # subscribe before enqueue to catch live events
    await q.enqueue("r1", ["a.py"])           # fire-and-forget (returns immediately)
    stages = [ev.stage async for ev in agen]  # drains until the terminal event
    assert stages[-1] == "done"
    final = await repo.get("r1")
    assert final.status == "done" and len(final.findings) == 1
