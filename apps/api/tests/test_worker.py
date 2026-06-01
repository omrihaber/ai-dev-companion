import pytest
from adc_api.agents import build_agents
from adc_api.corpus import CorpusStore, ingest_files
from adc_api.events import InMemoryEventBus
from adc_api.providers import MockProvider
from adc_api.repository import InMemoryReviewRepository
from adc_api.worker import run_review_core


@pytest.mark.asyncio
async def test_run_review_core_loads_corpus_and_saves_result(tmp_path):
    store = CorpusStore(str(tmp_path))
    store.write("rev1", ingest_files([{"path": "a.py", "content": "x = 1\n"}]))
    repo = InMemoryReviewRepository()
    await repo.create("rev1", "python")
    bus = InMemoryEventBus()
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }])

    await run_review_core(
        "rev1", ["a.py"], repo=repo, bus=bus, store=store,
        agents=build_agents(provider=provider),
    )
    result = await repo.get("rev1")
    assert result.status == "done"
    assert result.coverage.files_total == 1
    assert result.findings[0].location.file == "a.py"
