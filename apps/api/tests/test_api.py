import pytest
from adc_api.agents import build_agents
from adc_api.events import InMemoryEventBus
from adc_api.main import create_app
from adc_api.providers import MockProvider
from adc_api.queue import InlineReviewQueue
from adc_api.repository import InMemoryReviewRepository
from httpx import ASGITransport, AsyncClient


def _app():
    repo = InMemoryReviewRepository()
    bus = InMemoryEventBus()
    provider = MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "concat", "recommendation": "params", "start_line": 2, "end_line": 2,
    }])
    queue = InlineReviewQueue(
        repo, bus, agents_factory=lambda: build_agents(provider=provider)
    )
    return create_app(repo=repo, bus=bus, queue=queue)


@pytest.mark.asyncio
async def test_post_review_then_get_result():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/reviews", json={"language": "python", "code": "x=1\n"})
        assert r.status_code == 202
        review_id = r.json()["reviewId"]
        async with c.stream("GET", f"/api/reviews/{review_id}/events") as s:
            async for _ in s.aiter_lines():
                pass
        result = (await c.get(f"/api/reviews/{review_id}")).json()
        assert result["status"] == "done"
        assert any(f["category"] == "security" for f in result["findings"])


@pytest.mark.asyncio
async def test_post_review_rejects_unsupported_language():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/reviews", json={"language": "cobol", "code": "x"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_reviews_returns_created_review():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/api/reviews", json={"language": "python", "code": "x=1\n"})
        listing = (await c.get("/api/reviews")).json()
        assert isinstance(listing, list) and len(listing) >= 1
