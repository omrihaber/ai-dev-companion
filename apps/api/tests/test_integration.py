import os
import uuid

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


async def _docker_available() -> bool:
    from adc_api.scanners.docker_runner import docker_available
    return await docker_available()


@pytest.mark.asyncio
async def test_real_scanners_flag_sql_injection(tmp_path):
    if not await _docker_available():
        pytest.skip("Docker not available (run `task scanners-build` first)")

    import tempfile
    from pathlib import Path

    from adc_api.scanners.bandit import BanditScanner
    from adc_api.scanners.semgrep import SemgrepScanner

    code = (
        "def get_user(uid):\n"
        "    q = \"SELECT * FROM users WHERE id = \" + str(uid)\n"
        "    cursor.execute(q)\n"
    )
    with tempfile.TemporaryDirectory() as work_dir:
        (Path(work_dir) / "snippet.py").write_text(code)
        bandit = await BanditScanner().scan_path(work_dir)
        semgrep = await SemgrepScanner().scan_path(work_dir)
    all_findings = bandit + semgrep
    assert all_findings, "expected Semgrep and/or Bandit to report a finding"
    assert all(f.sources and f.sources[0].type == "tool" for f in all_findings)
    assert {f.sources[0].name for f in all_findings} <= {"bandit", "semgrep"}


@pytest.mark.asyncio
async def test_corpus_review_service_flags_sql_injection(tmp_path, monkeypatch):
    """Multi-file corpus review through ReviewService: real Semgrep/Bandit must flag vuln.py."""
    if not await _docker_available():
        pytest.skip("Docker not available (run `task scanners-build` first)")

    from adc_api.agents import build_agents
    from adc_api.corpus import CorpusStore, ingest_files
    from adc_api.providers import MockProvider
    from adc_api.review_service import ReviewService
    from adc_api.scanners import build_scanners
    from adc_api.settings import settings

    # Override the conftest autouse fixture that blanks settings.scanners.
    monkeypatch.setattr(settings, "scanners", "semgrep,bandit")

    vuln_code = (
        "def get_user(uid):\n"
        "    q = \"SELECT * FROM users WHERE id=\" + uid\n"
        "    cursor.execute(q)\n"
    )
    ok_code = (
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
    )

    review_id = f"itg-{uuid.uuid4().hex[:12]}"
    store = CorpusStore(str(tmp_path))
    corpus = ingest_files([
        {"path": "vuln.py", "content": vuln_code},
        {"path": "ok.py", "content": ok_code},
    ])
    store.write(review_id, corpus)

    svc = ReviewService(
        agents=build_agents(provider=MockProvider(seed=[])),
        scanners=build_scanners(),
    )

    events: list[ProgressEvent] = []
    result = await svc.run(
        review_id=review_id,
        files=store.list_files(review_id),
        marked={"vuln.py", "ok.py"},
        on_progress=events.append,
        work_dir=str(store.path(review_id)),
    )

    assert result.status == "done", f"review failed: {result.error}"
    assert result.findings, "expected at least one finding from the scanner layer"

    # At least one finding must be on vuln.py and carry a scanner source (bandit or semgrep).
    scanner_names = {"bandit", "semgrep"}
    vuln_scanner_findings = [
        f for f in result.findings
        if f.location.file == "vuln.py"
        and f.sources
        and any(s.name in scanner_names for s in f.sources)
    ]
    assert vuln_scanner_findings, (
        "expected a bandit or semgrep finding on vuln.py; "
        f"got findings: {[(f.location.file, [s.name for s in f.sources]) for f in result.findings]}"
    )
