# Inc 3: State & Queue Infrastructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move review state to Postgres and execution to an arq/Redis worker, with Redis pub/sub driving SSE — behind three testable seams (`ReviewRepository`, `EventBus`, `ReviewQueue`), leaving the API/Findings contract unchanged and making GET/History live + durable.

**Architecture:** API enqueues a job (after persisting `queued`) → arq worker runs the Inc 2 `ReviewService`, persisting each stage to Postgres and publishing `ProgressEvent`s to Redis → SSE subscribes to Redis (subscribe-then-snapshot, race-safe). Each seam has a prod adapter (SQLAlchemy / Redis / arq) and a test fake (in-memory / inline) so unit+API tests and CI need no real services.

**Tech Stack:** SQLAlchemy 2.0 async + asyncpg + Alembic (prod) / aiosqlite (tests), arq + redis, FastAPI + sse-starlette, pydantic-settings, pytest.

**Conventions:** TDD; run Python via `uv` from repo root; branch `inc3-state-queue-infra` (already created off `main`). API JSON stays camelCase; the Inc 2 `ReviewService`/graph/agents are unchanged.

---

## File Structure

```
apps/api/
├─ pyproject.toml                 # + sqlalchemy[asyncio], asyncpg, aiosqlite, alembic, arq, redis
├─ alembic.ini                    # NEW
├─ migrations/                    # NEW: env.py (async) + versions/0001_reviews.py
├─ src/adc_api/
│  ├─ settings.py                 # NEW: pydantic-settings (db/redis urls, code limits)
│  ├─ db/
│  │  ├─ models.py                # NEW: Base + ReviewRow (JSON.with_variant(JSONB))
│  │  └─ engine.py                # NEW: make_engine / make_session_factory
│  ├─ repository.py               # NEW: ReviewRepository Protocol + InMemory + Sql (+ _row_to_result)
│  ├─ events.py                   # NEW: EventBus Protocol + InMemoryEventBus + RedisEventBus
│  ├─ queue.py                    # NEW: ReviewQueue Protocol + InlineReviewQueue + ArqReviewQueue
│  ├─ worker.py                   # NEW: run_review_core + arq run_review task + WorkerSettings
│  ├─ main.py                     # MODIFY: create_app(repo,bus,queue); POST/SSE/GET use seams; race-safe SSE
│  └─ jobs.py                     # DELETE (replaced by repo+bus+queue)
│  └─ tests/{test_repository,test_events,test_queue,test_worker,test_api}.py  # + delete test_jobs.py
│  └─ tests/test_integration.py   # NEW: gated (requires services)
infra/compose/docker-compose.yml  # + redis service
Taskfile.yml                      # + migrate, worker
.env.example, README.md           # MODIFY
```

---

### Task 1: Dependencies + Settings

**Files:** Modify `apps/api/pyproject.toml`; Create `apps/api/src/adc_api/settings.py`; Test `apps/api/tests/test_settings.py`

- [ ] **Step 1: Add to `dependencies` in `apps/api/pyproject.toml`** (keep existing):

```toml
  "sqlalchemy[asyncio]>=2.0.30",
  "asyncpg>=0.29",
  "alembic>=1.13",
  "arq>=0.26",
  "redis>=5.0",
```
And add to the `dev` dependency-group: `"aiosqlite>=0.20"`.

- [ ] **Step 2: Sync + smoke import**

Run:
```bash
uv sync --all-packages
uv run python -c "import sqlalchemy, asyncpg, alembic, arq, redis, aiosqlite; print('ok', sqlalchemy.__version__)"
```
Expected: `ok 2.x`. If resolution fails, report exact error as BLOCKED.

- [ ] **Step 3: Write the failing test `apps/api/tests/test_settings.py`**

```python
from adc_api.settings import Settings


def test_settings_defaults_and_env_prefix(monkeypatch):
    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.redis_url.startswith("redis://")
    monkeypatch.setenv("ADC_REDIS_URL", "redis://example:6380")
    assert Settings().redis_url == "redis://example:6380"
```

- [ ] **Step 4: Run → fails** — `uv run pytest apps/api/tests/test_settings.py -v` → FAIL (no module).

- [ ] **Step 5: Implement `apps/api/src/adc_api/settings.py`**

```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADC_", extra="ignore")

    # "infra" = Postgres + Redis + arq worker (production). "memory" = in-process repo/bus +
    # inline execution (no services) — used by the e2e and a quick local/demo run.
    backend: str = "infra"
    database_url: str = "postgresql+asyncpg://adc:adc@localhost:5432/adc"
    redis_url: str = "redis://localhost:6379"
    max_code_bytes: int = 100_000
    max_code_lines: int = 2_000


settings = Settings()
```

- [ ] **Step 6: Run → passes** — `uv run pytest apps/api/tests/test_settings.py -v` → 1 passed. Then `uv run ruff check apps/api/src/adc_api/settings.py apps/api/tests/test_settings.py`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/pyproject.toml uv.lock apps/api/src/adc_api/settings.py apps/api/tests/test_settings.py
git commit -m "build(api): add sqlalchemy/asyncpg/alembic/arq/redis deps + Settings"
```

---

### Task 2: DB models + engine

**Files:** Create `apps/api/src/adc_api/db/__init__.py`, `apps/api/src/adc_api/db/models.py`, `apps/api/src/adc_api/db/engine.py`; Test `apps/api/tests/test_db_models.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_db_models.py`**

```python
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from adc_api.db.models import Base, ReviewRow


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
```

- [ ] **Step 2: Run → fails** — `uv run pytest apps/api/tests/test_db_models.py -v` → FAIL (no module).

- [ ] **Step 3: Create `apps/api/src/adc_api/db/__init__.py`** (empty file).

- [ ] **Step 4: Implement `apps/api/src/adc_api/db/models.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on Postgres, JSON elsewhere (SQLite in tests).
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class ReviewRow(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="queued")
    language: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String, default="pending")
    summary: Mapped[str] = mapped_column(String, default="")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    findings: Mapped[list] = mapped_column(_JSON, default=list)
```

- [ ] **Step 5: Implement `apps/api/src/adc_api/db/engine.py`**

```python
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, future=True, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 6: Run → passes** — `uv run pytest apps/api/tests/test_db_models.py -v` → 1 passed. Then `uv run ruff check apps/api/src/adc_api/db`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/adc_api/db apps/api/tests/test_db_models.py
git commit -m "feat(api): SQLAlchemy Base + ReviewRow (JSONB findings) + async engine"
```

---

### Task 3: ReviewRepository (Protocol + InMemory + Sql)

**Files:** Create `apps/api/src/adc_api/repository.py`; Test `apps/api/tests/test_repository.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_repository.py`**

```python
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from adc_core.models import Finding, Location, ReviewResult, Source
from adc_api.db.models import Base
from adc_api.repository import InMemoryReviewRepository, SqlReviewRepository


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
```

- [ ] **Step 2: Run → fails** — `uv run pytest apps/api/tests/test_repository.py -v` → FAIL (no module).

- [ ] **Step 3: Implement `apps/api/src/adc_api/repository.py`**

```python
from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from adc_core.models import Finding, ReviewResult, ReviewStatus

from adc_api.db.models import ReviewRow


def _row_to_result(row: ReviewRow) -> ReviewResult:
    return ReviewResult(
        id=row.id,
        status=row.status,  # type: ignore[arg-type]
        language=row.language,
        model=row.model,
        findings=[Finding.model_validate(f) for f in (row.findings or [])],
        summary=row.summary,
        created_at=row.created_at,
        duration_ms=row.duration_ms,
        error=row.error,
    )


class ReviewRepository(Protocol):
    async def create(self, review_id: str, language: str) -> None: ...
    async def set_status(self, review_id: str, status: ReviewStatus) -> None: ...
    async def save_result(self, result: ReviewResult) -> None: ...
    async def get(self, review_id: str) -> ReviewResult | None: ...
    async def list_all(self) -> list[ReviewResult]: ...


class InMemoryReviewRepository:
    def __init__(self) -> None:
        self._d: dict[str, ReviewResult] = {}

    async def create(self, review_id: str, language: str) -> None:
        self._d[review_id] = ReviewResult(id=review_id, language=language, model="pending")

    async def set_status(self, review_id: str, status: ReviewStatus) -> None:
        if review_id in self._d:
            self._d[review_id].status = status

    async def save_result(self, result: ReviewResult) -> None:
        existing = self._d.get(result.id)
        if existing is not None:
            result.created_at = existing.created_at
        self._d[result.id] = result

    async def get(self, review_id: str) -> ReviewResult | None:
        return self._d.get(review_id)

    async def list_all(self) -> list[ReviewResult]:
        return sorted(self._d.values(), key=lambda r: r.created_at, reverse=True)


class SqlReviewRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def create(self, review_id: str, language: str) -> None:
        async with self._sf() as s, s.begin():
            s.add(ReviewRow(id=review_id, status="queued", language=language))

    async def set_status(self, review_id: str, status: ReviewStatus) -> None:
        async with self._sf() as s, s.begin():
            row = await s.get(ReviewRow, review_id)
            if row is not None:
                row.status = status

    async def save_result(self, result: ReviewResult) -> None:
        async with self._sf() as s, s.begin():
            row = await s.get(ReviewRow, result.id)
            if row is None:
                row = ReviewRow(id=result.id, created_at=result.created_at)
                s.add(row)
            row.status = result.status
            row.language = result.language
            row.model = result.model
            row.summary = result.summary
            row.error = result.error
            row.duration_ms = result.duration_ms
            row.findings = [f.model_dump(by_alias=True, mode="json") for f in result.findings]

    async def get(self, review_id: str) -> ReviewResult | None:
        async with self._sf() as s:
            row = await s.get(ReviewRow, review_id)
            return _row_to_result(row) if row is not None else None

    async def list_all(self) -> list[ReviewResult]:
        async with self._sf() as s:
            rows = (
                await s.execute(select(ReviewRow).order_by(ReviewRow.created_at.desc()))
            ).scalars().all()
            return [_row_to_result(r) for r in rows]
```

- [ ] **Step 4: Run → passes** — `uv run pytest apps/api/tests/test_repository.py -v` → 2 passed (both repo impls). Then `uv run ruff check apps/api/src/adc_api/repository.py apps/api/tests/test_repository.py` (fix import order if flagged).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/repository.py apps/api/tests/test_repository.py
git commit -m "feat(api): ReviewRepository (Protocol + InMemory + SQLAlchemy) with findings JSON roundtrip"
```

---

### Task 4: EventBus (Protocol + InMemory + Redis)

**Files:** Create `apps/api/src/adc_api/events.py`; Test `apps/api/tests/test_events.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_events.py`**

```python
import pytest
from adc_api.events import InMemoryEventBus
from adc_api.schemas import ProgressEvent


@pytest.mark.asyncio
async def test_subscribe_receives_published_until_terminal():
    bus = InMemoryEventBus()
    agen = await bus.subscribe("r1")
    await bus.publish("r1", ProgressEvent(review_id="r1", stage="analyzing"))
    await bus.publish("r1", ProgressEvent(review_id="r1", stage="done"))
    seen = [ev.stage async for ev in agen]
    assert seen == ["analyzing", "done"]  # stops after terminal


@pytest.mark.asyncio
async def test_publish_with_no_subscriber_is_noop():
    bus = InMemoryEventBus()
    await bus.publish("nobody", ProgressEvent(review_id="nobody", stage="done"))  # must not raise
```

- [ ] **Step 2: Run → fails** — `uv run pytest apps/api/tests/test_events.py -v` → FAIL (no module).

- [ ] **Step 3: Implement `apps/api/src/adc_api/events.py`**

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from adc_api.schemas import ProgressEvent

_TERMINAL = {"done", "failed"}


class EventBus(Protocol):
    async def publish(self, review_id: str, event: ProgressEvent) -> None: ...
    async def subscribe(self, review_id: str) -> AsyncIterator[ProgressEvent]: ...


class InMemoryEventBus:
    """In-process pub/sub for tests/inline execution."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[ProgressEvent]]] = {}

    async def publish(self, review_id: str, event: ProgressEvent) -> None:
        for q in list(self._subs.get(review_id, [])):
            q.put_nowait(event)

    async def subscribe(self, review_id: str) -> AsyncIterator[ProgressEvent]:
        q: asyncio.Queue[ProgressEvent] = asyncio.Queue()
        self._subs.setdefault(review_id, []).append(q)  # registered before this coroutine returns

        async def _gen() -> AsyncIterator[ProgressEvent]:
            try:
                while True:
                    ev = await q.get()
                    yield ev
                    if ev.stage in _TERMINAL:
                        return
            finally:
                self._subs.get(review_id, []).remove(q)

        return _gen()


class RedisEventBus:
    """Cross-process pub/sub via Redis. Channel = review:{id}."""

    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(redis_url)

    @staticmethod
    def _channel(review_id: str) -> str:
        return f"review:{review_id}"

    async def publish(self, review_id: str, event: ProgressEvent) -> None:
        await self._redis.publish(self._channel(review_id), event.model_dump_json(by_alias=True))

    async def subscribe(self, review_id: str) -> AsyncIterator[ProgressEvent]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(review_id))

        async def _gen() -> AsyncIterator[ProgressEvent]:
            try:
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    ev = ProgressEvent.model_validate_json(msg["data"])
                    yield ev
                    if ev.stage in _TERMINAL:
                        return
            finally:
                await pubsub.unsubscribe(self._channel(review_id))
                await pubsub.aclose()

        return _gen()
```

- [ ] **Step 4: Run → passes** — `uv run pytest apps/api/tests/test_events.py -v` → 2 passed. (RedisEventBus is covered by the gated integration test in Task 8, not here.) Then `uv run ruff check apps/api/src/adc_api/events.py apps/api/tests/test_events.py`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/adc_api/events.py apps/api/tests/test_events.py
git commit -m "feat(api): EventBus (Protocol + InMemory + Redis pub/sub) for SSE progress"
```

---
### Task 5: Worker (run_review_core + arq) + ReviewQueue

**Files:** Create `apps/api/src/adc_api/worker.py`, `apps/api/src/adc_api/queue.py`; Test `apps/api/tests/test_worker.py`, `apps/api/tests/test_queue.py`

- [ ] **Step 1: Write the failing test `apps/api/tests/test_worker.py`**

```python
import asyncio

import pytest
from adc_api.agents import build_agents
from adc_api.events import InMemoryEventBus
from adc_api.providers import MockProvider
from adc_api.repository import InMemoryReviewRepository
from adc_api.worker import run_review_core


@pytest.mark.asyncio
async def test_run_review_core_persists_final_and_publishes_progress():
    repo = InMemoryReviewRepository()
    bus = InMemoryEventBus()
    await repo.create("r1", "python")
    agen = await bus.subscribe("r1")  # subscribe before the run so we see live events
    agents = build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 2, "end_line": 2,
    }]))
    task = asyncio.create_task(
        run_review_core("r1", "python", "x = 1\n", repo=repo, bus=bus, agents=agents)
    )
    stages = [ev.stage async for ev in agen]
    await task
    assert "analyzing" in stages and stages[-1] == "done"   # terminal published after save
    final = await repo.get("r1")
    assert final.status == "done" and len(final.findings) == 1  # 6 agents -> merged into one card
```

- [ ] **Step 2: Run → fails** — `uv run pytest apps/api/tests/test_worker.py -v` → FAIL (no module).

- [ ] **Step 3: Implement `apps/api/src/adc_api/worker.py`**

```python
from __future__ import annotations

import asyncio

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.events import EventBus, RedisEventBus
from adc_api.repository import ReviewRepository, SqlReviewRepository
from adc_api.review_service import ReviewService
from adc_api.schemas import ProgressEvent

_TERMINAL = {"done", "failed"}


async def run_review_core(
    review_id: str,
    language: str,
    code: str,
    *,
    repo: ReviewRepository,
    bus: EventBus,
    agents: list[SpecialistAgent],
) -> None:
    """Run the multi-agent review, persisting non-terminal stages + publishing them live, then
    save the final result and publish the terminal event LAST (so a GET after the SSE 'done' sees
    the saved findings)."""
    events: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()

    def on_progress(event: ProgressEvent) -> None:
        events.put_nowait(event)

    async def drain() -> None:
        while True:
            ev = await events.get()
            if ev is None:
                return
            if ev.stage not in _TERMINAL:  # terminal handled after save_result
                await repo.set_status(review_id, ev.stage)
                await bus.publish(review_id, ev)

    drain_task = asyncio.create_task(drain())
    svc = ReviewService(agents=agents)
    result = await svc.run(review_id=review_id, language=language, code=code, on_progress=on_progress)
    events.put_nowait(None)
    await drain_task

    await repo.save_result(result)
    await bus.publish(review_id, ProgressEvent(review_id=review_id, stage=result.status))


# ---- arq task + worker settings (production) ----

async def run_review(ctx: dict, review_id: str, language: str, code: str) -> None:
    await run_review_core(
        review_id, language, code, repo=ctx["repo"], bus=ctx["bus"], agents=build_agents()
    )


async def _on_startup(ctx: dict) -> None:
    from adc_api.db.engine import make_engine, make_session_factory
    from adc_api.settings import settings

    ctx["repo"] = SqlReviewRepository(make_session_factory(make_engine(settings.database_url)))
    ctx["bus"] = RedisEventBus(settings.redis_url)


def _redis_settings():
    from arq.connections import RedisSettings

    from adc_api.settings import settings

    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    functions = [run_review]
    on_startup = _on_startup
    redis_settings = _redis_settings()
    max_tries = 1
```

- [ ] **Step 4: Run → passes** — `uv run pytest apps/api/tests/test_worker.py -v` → 1 passed.

- [ ] **Step 5: Write the failing test `apps/api/tests/test_queue.py`**

```python
import pytest
from adc_api.agents import build_agents
from adc_api.events import InMemoryEventBus
from adc_api.providers import MockProvider
from adc_api.queue import InlineReviewQueue
from adc_api.repository import InMemoryReviewRepository


@pytest.mark.asyncio
async def test_inline_queue_runs_review_immediately():
    repo = InMemoryReviewRepository()
    bus = InMemoryEventBus()
    await repo.create("r1", "python")
    q = InlineReviewQueue(repo, bus, agents_factory=lambda: build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "d", "recommendation": "r", "start_line": 1, "end_line": 1,
    }])))
    await q.enqueue("r1", "python", "x = 1\n")
    final = await repo.get("r1")
    assert final.status == "done" and len(final.findings) == 1
```

- [ ] **Step 6: Run → fails** — `uv run pytest apps/api/tests/test_queue.py -v` → FAIL (no module).

- [ ] **Step 7: Implement `apps/api/src/adc_api/queue.py`**

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.events import EventBus
from adc_api.repository import ReviewRepository
from adc_api.worker import run_review_core


class ReviewQueue(Protocol):
    async def enqueue(self, review_id: str, language: str, code: str) -> None: ...


class InlineReviewQueue:
    """Runs the review immediately in-process (tests / the 'memory' backend / quick demo)."""

    def __init__(
        self,
        repo: ReviewRepository,
        bus: EventBus,
        agents_factory: Callable[[], list[SpecialistAgent]] = build_agents,
    ) -> None:
        self._repo = repo
        self._bus = bus
        self._agents_factory = agents_factory

    async def enqueue(self, review_id: str, language: str, code: str) -> None:
        await run_review_core(
            review_id, language, code,
            repo=self._repo, bus=self._bus, agents=self._agents_factory(),
        )


class ArqReviewQueue:
    """Enqueues the `run_review` job onto the arq/Redis queue (production)."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def enqueue(self, review_id: str, language: str, code: str) -> None:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        try:
            await pool.enqueue_job("run_review", review_id, language, code)
        finally:
            await pool.aclose()
```

- [ ] **Step 8: Run → passes** — `uv run pytest apps/api/tests/test_queue.py -v` → 1 passed. Then `uv run ruff check apps/api/src/adc_api/worker.py apps/api/src/adc_api/queue.py apps/api/tests/test_worker.py apps/api/tests/test_queue.py`.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/adc_api/worker.py apps/api/src/adc_api/queue.py apps/api/tests/test_worker.py apps/api/tests/test_queue.py
git commit -m "feat(api): worker (run_review_core + arq) + ReviewQueue (inline + arq)"
```

---

### Task 6: Rewire the API to repo + bus + queue (race-safe SSE)

**Files:** Modify `apps/api/src/adc_api/main.py`; Delete `apps/api/src/adc_api/jobs.py`, `apps/api/tests/test_jobs.py`; Modify `apps/api/tests/test_api.py`

- [ ] **Step 1: Replace `apps/api/tests/test_api.py`**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from adc_api.agents import build_agents
from adc_api.events import InMemoryEventBus
from adc_api.main import create_app
from adc_api.providers import MockProvider
from adc_api.queue import InlineReviewQueue
from adc_api.repository import InMemoryReviewRepository


def _app():
    repo = InMemoryReviewRepository()
    bus = InMemoryEventBus()
    queue = InlineReviewQueue(repo, bus, agents_factory=lambda: build_agents(provider=MockProvider(seed=[{
        "category": "security", "severity": "high", "title": "SQLi",
        "description": "concat", "recommendation": "params", "start_line": 2, "end_line": 2,
    }])))
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
```

- [ ] **Step 2: Delete the old job manager + its test**

```bash
git rm apps/api/src/adc_api/jobs.py apps/api/tests/test_jobs.py
```

- [ ] **Step 3: Run → fails** — `uv run pytest apps/api/tests/test_api.py -v` → FAIL (create_app still takes `agents_factory`, not repo/bus/queue).

- [ ] **Step 4: Replace `apps/api/src/adc_api/main.py`**

```python
from __future__ import annotations

import json
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from adc_core.sanitization import SubmissionError, validate_submission

from adc_api.events import EventBus, InMemoryEventBus, RedisEventBus
from adc_api.queue import ArqReviewQueue, InlineReviewQueue, ReviewQueue
from adc_api.repository import InMemoryReviewRepository, ReviewRepository, SqlReviewRepository
from adc_api.schemas import ReviewRequest
from adc_api.settings import settings

_TERMINAL = {"done", "failed"}


def _default_deps() -> tuple[ReviewRepository, EventBus, ReviewQueue]:
    if settings.backend == "memory":
        repo: ReviewRepository = InMemoryReviewRepository()
        bus: EventBus = InMemoryEventBus()
        return repo, bus, InlineReviewQueue(repo, bus)
    from adc_api.db.engine import make_engine, make_session_factory

    repo = SqlReviewRepository(make_session_factory(make_engine(settings.database_url)))
    bus = RedisEventBus(settings.redis_url)
    return repo, bus, ArqReviewQueue(settings.redis_url)


def create_app(
    repo: ReviewRepository | None = None,
    bus: EventBus | None = None,
    queue: ReviewQueue | None = None,
) -> FastAPI:
    if repo is None or bus is None or queue is None:
        d_repo, d_bus, d_queue = _default_deps()
        repo, bus, queue = repo or d_repo, bus or d_bus, queue or d_queue

    app = FastAPI(title="AI Dev Companion API")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.post("/api/reviews", status_code=202)
    async def create_review(req: ReviewRequest) -> dict:
        try:
            code = validate_submission(
                req.language, req.code,
                max_bytes=settings.max_code_bytes, max_lines=settings.max_code_lines,
            )
        except SubmissionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        review_id = str(uuid.uuid4())
        await repo.create(review_id, req.language)
        await queue.enqueue(review_id, req.language, code)
        return {"reviewId": review_id, "status": "queued"}

    @app.get("/api/reviews/{review_id}/events")
    async def review_events(review_id: str) -> EventSourceResponse:
        if await repo.get(review_id) is None:
            raise HTTPException(status_code=404, detail="review not found")

        async def gen():
            agen = await bus.subscribe(review_id)  # subscribe BEFORE snapshot (race-safe)
            snap = await repo.get(review_id)
            if snap is not None and snap.status in _TERMINAL:
                yield {"event": "progress",
                       "data": json.dumps({"reviewId": review_id, "stage": snap.status})}
                yield {"event": "complete", "data": "{}"}
                await agen.aclose()
                return
            async for ev in agen:
                yield {"event": "progress",
                       "data": json.dumps(ev.model_dump(by_alias=True), default=str)}
            yield {"event": "complete", "data": "{}"}

        return EventSourceResponse(gen())

    @app.get("/api/reviews")
    async def list_reviews() -> list[dict]:
        return [r.model_dump(by_alias=True, mode="json") for r in await repo.list_all()]

    @app.get("/api/reviews/{review_id}")
    async def get_review(review_id: str) -> dict:
        result = await repo.get(review_id)
        if result is None:
            raise HTTPException(status_code=404, detail="review not found")
        return result.model_dump(by_alias=True, mode="json")

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 5: Run → passes** — `uv run pytest apps/api/tests/test_api.py -v` → 3 passed. Then the whole suite: `uv run pytest packages/core apps/api -q` → all pass. Then `uv run ruff check .` → clean.

NOTE: `app = create_app()` uses `settings.backend` (default `infra`) → builds Sql/Redis/Arq deps. These are lazy (no connection at import), so import stays network-free. Confirm: `ADC_BACKEND=infra uv run python -c "import adc_api.main; print('ok')"` and `ADC_BACKEND=memory uv run python -c "from adc_api.main import create_app; create_app(); print('ok mem')"`.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/adc_api/main.py apps/api/tests/test_api.py
git commit -m "refactor(api): drive reviews via repository + event bus + queue (race-safe SSE); drop JobManager"
```

---

### Task 7: Alembic migration + Redis service + Taskfile + env/docs

**Files:** Create `apps/api/alembic.ini`, `apps/api/migrations/env.py`, `apps/api/migrations/versions/0001_create_reviews.py`; Modify `infra/compose/docker-compose.yml`, `Taskfile.yml`, `.env.example`, `README.md`

- [ ] **Step 1: Create `apps/api/alembic.ini`**

```ini
[alembic]
script_location = migrations
sqlalchemy.url = postgresql+asyncpg://adc:adc@localhost:5432/adc
```

- [ ] **Step 2: Create `apps/api/migrations/env.py`** (async; URL comes from Settings)

```python
import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from adc_api.db.models import Base
from adc_api.settings import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async_migrations())
```

- [ ] **Step 3: Create `apps/api/migrations/versions/0001_create_reviews.py`**

```python
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.String(), nullable=False, server_default=""),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("findings", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("reviews")
```

- [ ] **Step 4: Add a `redis` service to `infra/compose/docker-compose.yml`** (under `services:`, alongside postgres/ollama):

```yaml
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

- [ ] **Step 5: Add `migrate` + `worker` tasks to `Taskfile.yml`** (under `tasks:`)

```yaml
  migrate: { dir: apps/api, cmds: ["uv run alembic upgrade head"] }
  worker: { dir: apps/api, cmds: ["uv run arq adc_api.worker.WorkerSettings"] }
```

- [ ] **Step 6: Update `.env.example`** — change the DB URL to the async driver and add backend/redis. Replace the line `ADC_DATABASE_URL=postgresql://adc:adc@localhost:5432/adc` with:

```bash
ADC_DATABASE_URL=postgresql+asyncpg://adc:adc@localhost:5432/adc
ADC_REDIS_URL=redis://localhost:6379
# Backend: "infra" (Postgres+Redis+arq worker) | "memory" (in-process, no services — quick demo/e2e)
ADC_BACKEND=infra
```

- [ ] **Step 7: Update `README.md`** — (a) Architecture `apps/api` bullet to mention Postgres + arq/Redis worker; (b) Quick start now:

```markdown
## Quick start
\`\`\`bash
cp .env.example .env
task up            # postgres + redis + ollama
task migrate       # create the reviews table (alembic)
task pull-model    # qwen2.5-coder:7b  (or set ADC_MODEL_PROVIDER=openai/anthropic + a key)
task api           # http://localhost:8000
task worker        # arq worker (runs the reviews)
task web           # http://localhost:5173
\`\`\`
> No Postgres/Redis? Run the lightweight in-process mode: set \`ADC_BACKEND=memory\` and skip
> \`task migrate\`/\`task worker\` — reviews run inside the API process (non-durable; good for a quick demo).
```

- [ ] **Step 8: Validate config parses + commit**

Run: `docker compose -f infra/compose/docker-compose.yml config -q` (exit 0) and
`uv run python -c "from adc_api.db.models import Base; print(sorted(Base.metadata.tables))"` (prints `['reviews']`).
```bash
git add apps/api/alembic.ini apps/api/migrations infra/compose/docker-compose.yml Taskfile.yml .env.example README.md
git commit -m "feat(infra): alembic reviews migration, redis service, task migrate/worker, env+README"
```

---

### Task 8: e2e on memory backend + gated integration + final verification

**Files:** Modify `apps/web/playwright.config.ts`; Create `apps/api/tests/test_integration.py`; Modify `apps/api/pyproject.toml` (pytest marker)

- [ ] **Step 1: Point the Playwright API server at the memory backend** — in `apps/web/playwright.config.ts`, change the API `webServer.command` to set `ADC_BACKEND=memory` (so the e2e needs no Postgres/Redis/worker):

```ts
      command: "ADC_MODEL_PROVIDER=mock ADC_BACKEND=memory uv run --project ../../apps/api uvicorn adc_api.main:app --port 8001",
```

- [ ] **Step 2: Register the `integration` marker in `apps/api/pyproject.toml`** — add under `[tool.pytest.ini_options]` (create the table if absent; note the root `pyproject.toml` already sets pytest options, so add this to the **api** package file only if it has its own, otherwise add the marker to the root `pyproject.toml` `[tool.pytest.ini_options]`):

```toml
markers = ["integration: requires live Postgres + Redis (run with `task up`)"]
```

- [ ] **Step 3: Create `apps/api/tests/test_integration.py`** (self-skips when services aren't reachable, so default CI stays green)

```python
import os

import pytest

from adc_core.models import Finding, Location, ReviewResult, Source
from adc_api.schemas import ProgressEvent

pytestmark = pytest.mark.integration

DB_URL = os.getenv("ADC_DATABASE_URL", "postgresql+asyncpg://adc:adc@localhost:5432/adc")
REDIS_URL = os.getenv("ADC_REDIS_URL", "redis://localhost:6379")


async def _pg_available() -> bool:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        eng = create_async_engine(DB_URL)
        async with eng.connect():
            pass
        await eng.dispose()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_sql_repo_and_redis_bus_roundtrip_against_real_services():
    if not await _pg_available():
        pytest.skip("Postgres/Redis not available (run `task up` + `task migrate`)")

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from adc_api.db.models import Base
    from adc_api.events import RedisEventBus
    from adc_api.repository import SqlReviewRepository

    eng = create_async_engine(DB_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = SqlReviewRepository(async_sessionmaker(eng, expire_on_commit=False))

    await repo.create("itg1", "python")
    await repo.save_result(ReviewResult(
        id="itg1", status="done", language="python", model="m", summary="1 security",
        findings=[Finding(
            id="f", category="security", severity="high", title="t", description="d",
            recommendation="r", location=Location(start_line=1, end_line=1),
            sources=[Source(type="agent", name="security-agent")],
        )],
    ))
    got = await repo.get("itg1")
    assert got.status == "done" and got.findings[0].category == "security"

    bus = RedisEventBus(REDIS_URL)
    agen = await bus.subscribe("itg1")
    await bus.publish("itg1", ProgressEvent(review_id="itg1", stage="done"))
    seen = [ev.stage async for ev in agen]
    assert seen == ["done"]
    await eng.dispose()
```

- [ ] **Step 4: FULL verification (no services needed — integration self-skips)**

```bash
uv run pytest packages/core apps/api -q          # all unit/API pass; integration SKIPS
uv run ruff check .                              # clean
pnpm --filter web test -- --run                  # 4 passed (frontend unchanged)
pnpm --filter web exec tsc --noEmit              # clean
pnpm --filter web build                          # succeeds
find apps/web/src \( -name '*.js' -o -name '*.d.ts' \)   # empty
```
Then the e2e (ensure nothing is bound to :5173/:8000/:8001 first; Playwright starts a memory-backend mock API):
```bash
pnpm --filter web e2e   # 1 passed
rm -rf apps/web/test-results
```
If any step fails, STOP and report verbatim.

- [ ] **Step 5: Commit**

```bash
git add apps/web/playwright.config.ts apps/api/tests/test_integration.py apps/api/pyproject.toml
git commit -m "test: e2e on memory backend + gated Postgres/Redis integration test"
```

---

## Self-Review (completed)

**Spec coverage:** §2.1 seams → Repository (T3), EventBus (T4), Queue (T5); §2.2 SQLAlchemy/JSONB/Alembic → T2 (models/engine) + T7 (migration); §2.3 worker + sync→async drain bridge + save-before-terminal ordering → T5 (`run_review_core`) + arq `WorkerSettings`; §2.4 race-safe SSE (subscribe-then-snapshot) → T6; §3 contract unchanged + live/durable GET/History → T6 (reads repo) + T3; §4 local deploy (redis service, `task migrate`/`worker`, env) → T7; §5 testing (in-memory/SQLite fakes, gated integration) → T3/T4/T5/T6 + T8. The `memory` backend (T1 setting + T6 wiring) keeps the e2e service-free (T8).

**Placeholder scan:** none — every code step is complete; commands have expected output.

**Type consistency:** `ReviewRepository` methods (`create/set_status/save_result/get/list_all`) identical across Protocol + InMemory + Sql (T3) and consumers (T5 worker, T6 main, T8). `EventBus.publish/subscribe` (async, returns AsyncIterator) consistent T4→T5→T6. `ReviewQueue.enqueue(review_id, language, code)` consistent T5→T6. `run_review_core(review_id, language, code, *, repo, bus, agents)` consistent T5→T5(queue)→T8. `ReviewRow` columns (T2) match `_row_to_result`/`save_result` (T3) and the Alembic migration (T7). `Settings.backend/database_url/redis_url` (T1) used in T6/T7/worker. `ProgressEvent`/`ReviewResult`/`Finding` reused unchanged from Inc 1–2.
