import pytest
from adc_api.agents import build_agents
from adc_api.jobs import JobManager
from adc_api.providers import MockProvider
from adc_core.sanitization import SubmissionError


@pytest.mark.asyncio
async def test_create_runs_review_and_streams_until_terminal():
    jm = JobManager(agents_factory=lambda: build_agents(provider=MockProvider(seed=[{
        "category": "quality", "severity": "low", "title": "t",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }])))
    review_id = jm.create(language="python", code="x=1\n", max_bytes=1000, max_lines=100)
    stages = []
    async for event in jm.stream(review_id):
        stages.append(event.stage)
    assert stages[-1] == "done"
    result = jm.get(review_id)
    # all six agents return the same seeded finding -> aggregator merges into one card
    assert result.status == "done" and len(result.findings) == 1

@pytest.mark.asyncio
async def test_create_rejects_bad_submission():
    jm = JobManager(agents_factory=lambda: build_agents(provider=MockProvider()))
    with pytest.raises(SubmissionError):
        jm.create(language="cobol", code="x", max_bytes=1000, max_lines=100)
