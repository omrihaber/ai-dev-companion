# Inc 3 — State & Queue Infrastructure — Design Spec

**Date:** 2026-05-31
**Status:** Approved (brainstorm) — pending implementation plan
**Builds on:** Inc 0–2 (merged to `main`)
**Repo:** https://github.com/omrihaber/ai-dev-companion

---

## 1. Overview

Move review **state** and **execution** out of the API process. Today `JobManager` keeps results in an
in-memory dict and runs reviews via `asyncio.create_task` with an in-process `asyncio.Queue` for SSE —
so nothing survives a restart and progress can't cross processes. Inc 3 introduces:

- **Postgres** persistence for reviews (durable history, accurate status).
- An **arq + Redis** queue + **worker process** that runs the Inc 2 multi-agent `ReviewService`.
- A **Redis pub/sub** event bus so the API's SSE endpoint streams progress emitted by the worker.

The **API contract and Findings schema are unchanged.** A side-effect: `GET /reviews` and History now
reflect live, durable state (fixing the Inc 1 "stuck on queued" snapshot wart).

### Guiding principles
- **Three clean seams** (`ReviewRepository`, `EventBus`, `ReviewQueue`) — each an interface with a prod
  adapter and a test fake, so unit/API tests need no real Postgres/Redis/worker.
- **The Inc 2 `ReviewService`/graph is unchanged** — the worker drives it.
- **Contract unchanged** for API consumers and the frontend.
- **TDD**, deterministic tests via in-memory/SQLite fakes; real adapters covered by a gated integration test.

---

## 2. Architecture

```
Browser ─POST─▶ API (FastAPI) ──enqueue──▶ Redis queue ──▶ arq Worker
   ▲             │  └─ repo.create(status=queued) ─▶ Postgres        │ runs ReviewService (Inc 2 graph)
   │ SSE         │                                                   │ • repo.set_status per stage ─▶ Postgres
   └─────────────┴── EventBus.subscribe("review:{id}") ◀──publish ProgressEvents (Redis)──┘
GET /reviews, /reviews/{id} ─repo.read─▶ Postgres (live + durable)
```

### 2.1 Seams (interfaces)
- **`ReviewRepository`** (`async`): `create(review_id, language) -> None`, `set_status(review_id, status, *, sub_status=None) -> None`, `save_result(result: ReviewResult) -> None`, `get(review_id) -> ReviewResult | None`, `list_all() -> list[ReviewResult]`.
  - Prod: `SqlReviewRepository` (SQLAlchemy async). Tests: `InMemoryReviewRepository` + the SQL impl unit-tested on SQLite.
- **`EventBus`** (`async`): `publish(review_id, event: ProgressEvent) -> None`, `subscribe(review_id) -> AsyncIterator[ProgressEvent]`.
  - Prod: `RedisEventBus` (pub/sub channel `review:{id}`, terminal event closes the stream). Tests: `InMemoryEventBus`.
- **`ReviewQueue`**: `async enqueue(review_id, language, code) -> None`.
  - Prod: `ArqReviewQueue` (enqueues the `run_review` job). Tests: `InlineReviewQueue` (runs the worker task immediately against the injected repo/bus/agents, so POST→SSE→GET works in-process).

### 2.2 Persistence (SQLAlchemy 2.0 async + Alembic)
A single `reviews` table:

| column | type | notes |
|---|---|---|
| id | str (PK) | uuid |
| status | str | ReviewStatus |
| language | str | |
| model | str | comma-joined agent models |
| summary | str | |
| error | str \| null | |
| duration_ms | int \| null | |
| created_at | datetime (tz) | |
| sub_status | JSON | per-agent progress (for live GET) |
| findings | `JSON().with_variant(JSONB, "postgresql")` | the `Finding[]` array |

Async engine via `asyncpg` (`ADC_DATABASE_URL`). One Alembic migration creates the table; applied via
`task migrate` (`alembic upgrade head`). Only `SqlReviewRepository` touches the ORM; it maps rows ⇄
`ReviewResult` (findings (de)serialized through the Pydantic models, preserving the camelCase contract).
Using `JSON().with_variant(JSONB, ...)` lets prod use JSONB while SQLite-backed tests use JSON.

### 2.3 Worker (arq) + status transitions
`apps/api/src/adc_api/worker.py`: arq `WorkerSettings` (Redis from `ADC_REDIS_URL`, `max_tries=1`) and:

```
async def run_review(ctx, review_id, language, code):
    repo, bus = ctx["repo"], ctx["bus"]
    agents = build_agents()
    svc = ReviewService(agents=agents)
    def on_progress(event):           # called by ReviewService per stage
        await repo.set_status(review_id, event.stage, sub_status=event.sub_status)  # via run_coroutine/queue
        await bus.publish(review_id, event)
    result = await svc.run(review_id=..., language=..., code=..., on_progress=on_progress)
    await repo.save_result(result)
    await bus.publish(review_id, terminal ProgressEvent)   # signals SSE complete
```

**Sync→async bridge (specified, not left open):** `ReviewService.run`'s `on_progress` is sync
(`Callable[[ProgressEvent], None]`, unchanged from Inc 2). The worker creates an `asyncio.Queue`; the
`on_progress` callback does `queue.put_nowait(event)` (sync). A concurrent `_drain` task — started
*before* `svc.run` — awaits `repo.set_status(...)` + `bus.publish(...)` for each event until a `None`
sentinel pushed after `svc.run` returns, then the worker `save_result`s the final `ReviewResult` and
publishes the terminal event. This preserves event order, keeps all I/O async, and mirrors the Inc 1
`JobManager` queue pattern. Net behavior: every emitted stage is persisted to Postgres AND published to Redis.

### 2.4 SSE endpoint (race-safe)
`GET /api/reviews/{id}/events`:
1. 404 if the review doesn't exist (repo.get).
2. **Subscribe to `review:{id}` first**, then read the snapshot. If already terminal (worker finished
   before the client connected), emit the final state + `complete` immediately. Otherwise stream
   published `ProgressEvent`s until a terminal stage, then `complete`.

This avoids both the missed-event race and hanging on an already-finished review.

---

## 3. API / UI impact (minimal)
- **Contract unchanged:** `POST /api/reviews` still returns `202 {reviewId}`; SSE event shape and
  `ReviewResult` JSON identical; `GET /reviews` + `/reviews/{id}` now read Postgres (live + durable).
- `POST` now: `repo.create(queued)` → `queue.enqueue(...)`. `create_app` wires repo+bus+queue (injectable).
- **Frontend:** no changes required. History now shows accurate, persisted statuses across restarts
  (also advances the Product/UX "history restore" item toward feasibility — out of scope here).

---

## 4. Local deploy & configuration
- **Compose:** add a `redis:7` service (Postgres+pgvector and Ollama already present).
- **Taskfile:** `task migrate` (alembic upgrade head); `task worker` (`arq adc_api.worker.WorkerSettings`);
  `task api`/`task web` unchanged; `task up` brings up postgres+redis(+ollama).
- **Config** (pydantic-settings): `ADC_DATABASE_URL` (default `postgresql+asyncpg://adc:adc@localhost:5432/adc`),
  `ADC_REDIS_URL` (default `redis://localhost:6379`). Documented in `.env.example` + README run steps
  (now: `task up` → `task migrate` → `task api` + `task worker` + `task web`).

---

## 5. Testing
- **Unit/API:** inject `InMemoryReviewRepository` + `InMemoryEventBus` + `InlineReviewQueue` (runs the
  worker task immediately). The existing POST→SSE→GET API test and the MockProvider/agent tests keep
  passing with **no Postgres/Redis/worker** required.
- **Repository:** `SqlReviewRepository` unit-tested against **SQLite** (`aiosqlite`) — create/set_status/
  save_result round-trip, findings JSON (de)serialization preserves the schema, list ordering.
- **Worker task:** call `run_review` directly with fake repo+bus+mock agents; assert status transitions
  persisted, progress published, final result saved (status done; failed path sets error).
- **SSE race:** test that subscribing after a review is already terminal still yields the final state.
- **Gated integration** (requires `task up`): real asyncpg repo + Redis bus + arq worker end-to-end; not
  in the default CI matrix (documented as a `make integration` / marked test).
- Determinism rule from Inc 1–2 holds (assert schema/stages, not LLM wording).

---

## 6. Out of scope (later increments)
- Multi-file + retrieval / pgvector embeddings (original "Inc 3" feature — re-sequenced; pgvector image is
  already in compose for when it lands).
- External SARIF scanners (Inc 5), auth (Inc 6), notifications (Inc 7), observability (Inc 8).
- In-app History "open a past review" UX (tech-debt) — enabled-by but not built here.

---

## 7. Known limitations
- Adds two required services (Postgres, Redis) + a worker process for the full local run; the test fakes
  keep development/CI light, but the demo now needs `task up` + `task migrate` + `task worker`.
- `max_tries=1`: a failed review is surfaced, not retried.
- The sync→async `on_progress` bridge in the worker is an implementation detail to get right (see §2.3).
