from __future__ import annotations

import json
import uuid

from adc_core.sanitization import SubmissionError, validate_submission
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

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
