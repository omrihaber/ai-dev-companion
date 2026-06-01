import pytest
from adc_api.db.models import Base, ReviewRow
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.mark.asyncio
async def test_review_row_roundtrips_findings_json():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as s, s.begin():
        s.add(ReviewRow(id="r1", status="queued", language="python", findings=[{"a": 1}]))
    async with sf() as s:
        row = await s.get(ReviewRow, "r1")
    assert row.status == "queued" and row.findings == [{"a": 1}]
