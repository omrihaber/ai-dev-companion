import pytest
from adc_api.agents import build_agents
from adc_api.corpus import CorpusFile
from adc_api.providers import MockProvider
from adc_api.review_service import ReviewService


def _files(*paths):
    return [CorpusFile(p, "x = 1\n", "python") for p in paths]


@pytest.mark.asyncio
async def test_per_file_findings_carry_file_and_merge_per_file():
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQL injection",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }]))
    svc = ReviewService(agents=agents, scanners=[])
    result = await svc.run(
        review_id="r1", files=_files("a.py", "b.py"), marked={"a.py", "b.py"},
        on_progress=lambda e: None,
    )
    assert result.status == "done"
    files = sorted(f.location.file for f in result.findings)
    assert files == ["a.py", "b.py"]
    assert result.coverage.files_total == 2
    assert result.coverage.files_agent_reviewed == 2


@pytest.mark.asyncio
async def test_skipped_files_recorded_in_coverage():
    agents = build_agents(provider=MockProvider(seed=[]))
    svc = ReviewService(agents=agents, scanners=[])
    result = await svc.run(
        review_id="r2", files=_files("a.py", "b.py", "c.py"), marked={"a.py"},
        on_progress=lambda e: None,
    )
    by = {c.path: c for c in result.coverage.files}
    assert by["a.py"].agent_reviewed and by["a.py"].reason == "marked"
    assert not by["b.py"].agent_reviewed and by["b.py"].reason == "not-flagged"
    assert result.coverage.files_agent_reviewed == 1


@pytest.mark.asyncio
async def test_all_agents_failing_surfaces_as_failed_not_clean():
    class _Boom(MockProvider):
        async def complete_structured(self, **kwargs):
            raise RuntimeError("auth error")

    svc = ReviewService(agents=build_agents(provider=_Boom()), scanners=[])
    stages: list[str] = []
    result = await svc.run(
        review_id="rf", files=_files("a.py"), marked={"a.py"},
        on_progress=lambda e: stages.append(e.stage),
    )
    assert result.status == "failed"
    assert "agents failed" in (result.error or "")
    assert stages[-1] == "failed"


@pytest.mark.asyncio
async def test_progress_reports_bounded_file_counts():
    agents = build_agents(provider=MockProvider(seed=[]))
    svc = ReviewService(agents=agents, scanners=[])
    subs: list[dict] = []
    await svc.run(
        review_id="rp", files=_files("a.py", "b.py"), marked={"a.py", "b.py"},
        on_progress=lambda e: subs.append(e.sub_status) if e.stage == "analyzing" else None,
    )
    last = subs[-1]
    assert last.get("filesTotal") == "2" and last.get("filesReviewed") == "2"
