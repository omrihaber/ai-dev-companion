from __future__ import annotations

import json
import uuid

from adc_core.sanitization import SubmissionError, validate_submission
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from adc_api.corpus import CorpusFile, CorpusStore, IngestError, ingest_files, ingest_zip
from adc_api.events import EventBus, InMemoryEventBus, RedisEventBus
from adc_api.queue import ArqReviewQueue, InlineReviewQueue, ReviewQueue
from adc_api.repository import InMemoryReviewRepository, ReviewRepository, SqlReviewRepository
from adc_api.schemas import ProgressEvent, ReviewRequest
from adc_api.settings import settings

_TERMINAL = {"done", "failed"}


class RerunRequest(BaseModel):
    marked: list[str] = []


def _default_deps() -> tuple[ReviewRepository, EventBus, ReviewQueue, CorpusStore]:
    store = CorpusStore(settings.work_root)
    if settings.backend == "memory":
        repo: ReviewRepository = InMemoryReviewRepository()
        bus: EventBus = InMemoryEventBus()
        return repo, bus, InlineReviewQueue(repo, bus, store), store
    from adc_api.db.engine import make_engine, make_session_factory

    repo = SqlReviewRepository(make_session_factory(make_engine(settings.database_url)))
    bus = RedisEventBus(settings.redis_url)
    return repo, bus, ArqReviewQueue(settings.redis_url), store


def _corpus_from_request(req: ReviewRequest) -> list[CorpusFile]:
    """Legacy {code,language} -> 1-file corpus; otherwise ingest files[]."""
    if req.files:
        return ingest_files([f.model_dump() for f in req.files])
    if req.code is not None and req.language is not None:
        code = validate_submission(
            req.language, req.code,
            max_bytes=settings.max_code_bytes, max_lines=settings.max_code_lines,
        )
        ext = {"python": "py", "typescript": "ts", "java": "java"}.get(req.language, "txt")
        return [CorpusFile(path=f"snippet.{ext}", content=code, language=req.language)]
    raise IngestError("provide either files[] or code+language")


def create_app(
    repo: ReviewRepository | None = None,
    bus: EventBus | None = None,
    queue: ReviewQueue | None = None,
    store: CorpusStore | None = None,
) -> FastAPI:
    if repo is None or bus is None or queue is None or store is None:
        d_repo, d_bus, d_queue, d_store = _default_deps()
        repo, bus, queue, store = repo or d_repo, bus or d_bus, queue or d_queue, store or d_store

    app = FastAPI(title="AI Dev Companion API")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    async def _start(files: list[CorpusFile], marked: list[str]) -> str:
        review_id = str(uuid.uuid4())
        store.write(review_id, files)
        await repo.create(review_id, (files[0].language or "text"))
        valid = {f.path for f in files}
        await queue.enqueue(review_id, [m for m in marked if m in valid])
        return review_id

    @app.post("/api/reviews", status_code=202)
    async def create_review(req: ReviewRequest) -> dict:
        try:
            files = _corpus_from_request(req)
        except (IngestError, SubmissionError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        marked = req.marked or [f.path for f in files]
        return {"reviewId": await _start(files, marked), "status": "queued"}

    @app.post("/api/reviews/zip", status_code=202)
    async def create_review_zip(file: UploadFile) -> dict:
        try:
            files = ingest_zip(await file.read())
        except IngestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"reviewId": await _start(files, [f.path for f in files]), "status": "queued"}

    @app.post("/api/reviews/{review_id}/rerun", status_code=202)
    async def rerun_review(review_id: str, req: RerunRequest) -> dict:
        if await repo.get(review_id) is None:
            raise HTTPException(status_code=404, detail="review not found")
        new_id = str(uuid.uuid4())
        store.copy(review_id, new_id)
        files = store.list_files(new_id)
        await repo.create(new_id, (files[0].language or "text") if files else "text")
        await repo.set_parent(new_id, review_id)
        valid = {f.path for f in files}
        await queue.enqueue(new_id, [m for m in req.marked if m in valid])
        return {"reviewId": new_id, "status": "queued", "parentReviewId": review_id}

    @app.get("/api/reviews/{review_id}/file")
    async def get_file(review_id: str, path: str) -> dict:
        try:
            return {"path": path, "content": store.read_file(review_id, path)}
        except IngestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/reviews/{review_id}/events")
    async def review_events(review_id: str) -> EventSourceResponse:
        if await repo.get(review_id) is None:
            raise HTTPException(status_code=404, detail="review not found")

        async def gen():
            agen = await bus.subscribe(review_id)
            snap = await repo.get(review_id)
            if snap is not None and snap.status in _TERMINAL:
                ev = ProgressEvent(review_id=review_id, stage=snap.status)
                yield {"event": "progress",
                       "data": json.dumps(ev.model_dump(by_alias=True), default=str)}
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
        out = []
        for r in await repo.list_all():
            d = r.model_dump(by_alias=True, mode="json")
            d["fileCount"] = r.coverage.files_total if r.coverage else 0
            out.append(d)
        return out

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
