import tempfile

import pytest
from adc_api.agents import build_agents
from adc_api.corpus import CorpusStore
from adc_api.events import InMemoryEventBus
from adc_api.main import create_app
from adc_api.providers import MockProvider
from adc_api.queue import InlineReviewQueue
from adc_api.repository import InMemoryReviewRepository
from httpx import ASGITransport, AsyncClient


def _app():
    repo = InMemoryReviewRepository()
    bus = InMemoryEventBus()
    store = CorpusStore(tempfile.mkdtemp())
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "concat", "recommendation": "params", "start_line": 1, "end_line": 1,
    }])
    queue = InlineReviewQueue(
        repo, bus, store, agents_factory=lambda: build_agents(provider=provider)
    )
    return create_app(repo=repo, bus=bus, queue=queue, store=store)


async def _drain(c, review_id):
    async with c.stream("GET", f"/api/reviews/{review_id}/events") as s:
        async for _ in s.aiter_lines():
            pass


@pytest.mark.asyncio
async def test_multifile_review_carries_files_and_coverage():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "x=1\n"}, {"path": "b.py", "content": "y=2\n"}],
            "marked": ["a.py", "b.py"],
        })
        assert r.status_code == 202
        rid = r.json()["reviewId"]
        await _drain(c, rid)
        result = (await c.get(f"/api/reviews/{rid}")).json()
        assert result["status"] == "done"
        assert result["coverage"]["filesTotal"] == 2
        assert {f["location"]["file"] for f in result["findings"]} == {"a.py", "b.py"}


@pytest.mark.asyncio
async def test_legacy_code_still_works_and_rejects_bad_language():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        ok = await c.post("/api/reviews", json={"language": "python", "code": "x=1\n"})
        assert ok.status_code == 202
        bad = await c.post("/api/reviews", json={"language": "cobol", "code": "x"})
        assert bad.status_code == 422


@pytest.mark.asyncio
async def test_get_file_serves_content_and_blocks_traversal():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        rid = (await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "hello\n"}], "marked": ["a.py"],
        })).json()["reviewId"]
        await _drain(c, rid)
        good = await c.get(f"/api/reviews/{rid}/file", params={"path": "a.py"})
        assert good.status_code == 200 and good.json()["content"] == "hello\n"
        bad = await c.get(f"/api/reviews/{rid}/file", params={"path": "../../etc/passwd"})
        assert bad.status_code == 400


@pytest.mark.asyncio
async def test_rerun_reuses_corpus_with_new_marks():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        rid = (await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "x=1\n"}, {"path": "b.py", "content": "y=2\n"}],
            "marked": ["a.py"],
        })).json()["reviewId"]
        await _drain(c, rid)
        rr = await c.post(f"/api/reviews/{rid}/rerun", json={"marked": ["a.py", "b.py"]})
        assert rr.status_code == 202
        rid2 = rr.json()["reviewId"]
        await _drain(c, rid2)
        result = (await c.get(f"/api/reviews/{rid2}")).json()
        assert result["parentReviewId"] == rid
        assert result["coverage"]["filesAgentReviewed"] == 2


@pytest.mark.asyncio
async def test_marks_over_ceiling_rejected_at_ingest(monkeypatch):
    from adc_api.settings import settings
    monkeypatch.setattr(settings, "agent_file_ceiling", 1)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "x=1\n"}, {"path": "b.py", "content": "y=2\n"}],
            "marked": ["a.py", "b.py"],
        })
        assert r.status_code == 422
        assert "Narrow your selection" in r.json()["detail"]


@pytest.mark.asyncio
async def test_list_includes_file_count():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        rid = (await c.post("/api/reviews", json={
            "files": [{"path": "a.py", "content": "x=1\n"}], "marked": ["a.py"],
        })).json()["reviewId"]
        await _drain(c, rid)
        listing = (await c.get("/api/reviews")).json()
        row = next(x for x in listing if x["id"] == rid)
        assert row["fileCount"] == 1


@pytest.mark.asyncio
async def test_settings_get_and_put_roundtrip(tmp_path, monkeypatch):
    from adc_api.settings import settings as _s
    monkeypatch.setattr(_s, "config_file", str(tmp_path / "cfg.json"))
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        put = await c.put("/api/settings", json={
            "provider": "openai", "model": "gpt-4o-mini", "apiKey": "sk-test-123456",
        })
        assert put.status_code == 200
        body = put.json()
        assert body["provider"] == "openai" and body["model"] == "gpt-4o-mini"
        assert body["hasKey"] is True and body["keyHint"] == "…3456"
        assert "sk-test" not in str(body)  # raw key never echoed
        got = (await c.get("/api/settings")).json()
        assert got["provider"] == "openai" and got["hasKey"] is True
