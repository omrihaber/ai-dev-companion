import os

import pytest
from adc_api.schemas import ProgressEvent
from adc_core.models import Finding, Location, ReviewResult, Source

pytestmark = pytest.mark.integration

DB_URL = os.getenv("ADC_DATABASE_URL", "postgresql+asyncpg://adc:adc@localhost:5432/adc")
REDIS_URL = os.getenv("ADC_REDIS_URL", "redis://localhost:6379")


async def _services_available() -> bool:
    """True only if BOTH Postgres and Redis are reachable (so partial availability still skips)."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        eng = create_async_engine(DB_URL)
        async with eng.connect():
            pass
        await eng.dispose()

        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_sql_repo_and_redis_bus_roundtrip_against_real_services():
    if not await _services_available():
        pytest.skip("Postgres+Redis not available (run `task up` + `task migrate`)")

    import uuid

    from adc_api.db.models import Base
    from adc_api.events import RedisEventBus
    from adc_api.repository import SqlReviewRepository
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    rid = f"itg-{uuid.uuid4().hex[:12]}"  # unique per run so the test is idempotent
    eng = create_async_engine(DB_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = SqlReviewRepository(async_sessionmaker(eng, expire_on_commit=False))

    try:
        await repo.create(rid, "python")
        await repo.save_result(ReviewResult(
            id=rid, status="done", language="python", model="m", summary="1 security",
            findings=[Finding(
                id="f", category="security", severity="high", title="t", description="d",
                recommendation="r", location=Location(start_line=1, end_line=1),
                sources=[Source(type="agent", name="security-agent")],
            )],
        ))
        got = await repo.get(rid)
        assert got.status == "done" and got.findings[0].category == "security"

        bus = RedisEventBus(REDIS_URL)
        agen = await bus.subscribe(rid)
        await bus.publish(rid, ProgressEvent(review_id=rid, stage="done"))
        seen = [ev.stage async for ev in agen]
        assert seen == ["done"]
    finally:
        async with eng.begin() as conn:
            await conn.execute(text("DELETE FROM reviews WHERE id = :id"), {"id": rid})
        await eng.dispose()
