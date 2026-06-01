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


@pytest.mark.asyncio
async def test_inmemory_roundtrips_coverage_and_parent():
    from adc_api.repository import InMemoryReviewRepository
    from adc_core.models import Coverage, FileCoverage, ReviewResult

    repo = InMemoryReviewRepository()
    await repo.create("r1", "python")
    cov = Coverage(files_total=2, files_agent_reviewed=1,
                   files=[FileCoverage(path="a.py", agent_reviewed=True, reason="marked")])
    await repo.save_result(ReviewResult(
        id="r1", status="done", language="python", model="m", coverage=cov,
        parent_review_id="p0",
    ))
    got = await repo.get("r1")
    assert got.coverage.files_total == 2 and got.parent_review_id == "p0"


@pytest.mark.asyncio
async def test_set_parent_preserved_through_save_result():
    from adc_api.repository import InMemoryReviewRepository
    from adc_core.models import ReviewResult

    repo = InMemoryReviewRepository()
    await repo.create("c1", "python")
    await repo.set_parent("c1", "parent1")
    # worker later saves a result WITHOUT a parent — it must not be nulled
    await repo.save_result(ReviewResult(id="c1", status="done", language="python", model="m"))
    assert (await repo.get("c1")).parent_review_id == "parent1"


@pytest.mark.asyncio
async def test_sql_roundtrips_coverage_and_parent():
    from adc_api.repository import SqlReviewRepository
    from adc_core.models import Coverage, FileCoverage, ReviewResult

    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = SqlReviewRepository(async_sessionmaker(engine, expire_on_commit=False))

    await repo.create("r2", "python")
    cov = Coverage(files_total=3, files_agent_reviewed=2,
                   files=[FileCoverage(path="b.py", agent_reviewed=True, reason="scanner-hit")])
    await repo.save_result(ReviewResult(
        id="r2", status="done", language="python", model="m", coverage=cov,
        parent_review_id="p99",
    ))
    got = await repo.get("r2")
    assert got.coverage.files_total == 3 and got.parent_review_id == "p99"


@pytest.mark.asyncio
async def test_sql_set_parent_preserved_through_save_result():
    from adc_api.repository import SqlReviewRepository
    from adc_core.models import ReviewResult

    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = SqlReviewRepository(async_sessionmaker(engine, expire_on_commit=False))

    await repo.create("c2", "python")
    await repo.set_parent("c2", "parentX")
    # worker later saves a result WITHOUT a parent — it must not be nulled
    await repo.save_result(ReviewResult(id="c2", status="done", language="python", model="m"))
    assert (await repo.get("c2")).parent_review_id == "parentX"
