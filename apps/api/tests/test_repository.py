import pytest
from adc_api.db.models import Base
from adc_api.repository import InMemoryReviewRepository, SqlReviewRepository
from adc_core.models import Finding, Location, ReviewResult, Source
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def _result(rid="r1"):
    return ReviewResult(
        id=rid, status="done", language="python", model="mock", summary="1 security",
        duration_ms=12,
        findings=[Finding(
            id="f1", category="security", severity="high", title="SQLi", description="d",
            recommendation="r", location=Location(start_line=2, end_line=2),
            sources=[Source(type="agent", name="security-agent")],
        )],
    )


async def _in_memory_repo():
    return InMemoryReviewRepository()


async def _sql_repo():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return SqlReviewRepository(async_sessionmaker(engine, expire_on_commit=False))


@pytest.mark.asyncio
@pytest.mark.parametrize("make_repo", [_in_memory_repo, _sql_repo])
async def test_create_set_status_save_and_read(make_repo):
    repo = await make_repo()
    await repo.create("r1", "python")
    got = await repo.get("r1")
    assert got.status == "queued" and got.language == "python"

    await repo.set_status("r1", "analyzing")
    assert (await repo.get("r1")).status == "analyzing"

    await repo.save_result(_result("r1"))
    final = await repo.get("r1")
    assert final.status == "done"
    assert final.findings[0].category == "security"
    assert final.findings[0].sources[0].name == "security-agent"

    listed = await repo.list_all()
    assert any(r.id == "r1" for r in listed)
