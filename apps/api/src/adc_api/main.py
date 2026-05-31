from __future__ import annotations

import json
import os
from collections.abc import Callable

from adc_core.sanitization import SubmissionError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from adc_api.jobs import JobManager
from adc_api.providers import ModelProvider, build_provider
from adc_api.schemas import ReviewRequest


def create_app(provider_factory: Callable[[], ModelProvider] | None = None) -> FastAPI:
    app = FastAPI(title="AI Dev Companion API")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    jm = JobManager(provider_factory=provider_factory or build_provider)
    max_bytes = int(os.getenv("ADC_MAX_CODE_BYTES", "100000"))
    max_lines = int(os.getenv("ADC_MAX_CODE_LINES", "2000"))

    @app.post("/api/reviews", status_code=202)
    async def create_review(req: ReviewRequest) -> dict:
        try:
            review_id = jm.create(
                language=req.language, code=req.code, max_bytes=max_bytes, max_lines=max_lines
            )
        except SubmissionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"reviewId": review_id, "status": "queued"}

    @app.get("/api/reviews/{review_id}/events")
    async def review_events(review_id: str) -> EventSourceResponse:
        if jm.get(review_id) is None:
            raise HTTPException(status_code=404, detail="review not found")

        async def gen():
            async for event in jm.stream(review_id):
                data = json.dumps(event.model_dump(by_alias=True), default=str)
                yield {"event": "progress", "data": data}
            yield {"event": "complete", "data": "{}"}

        return EventSourceResponse(gen())

    @app.get("/api/reviews/{review_id}")
    async def get_review(review_id: str) -> dict:
        result = jm.get(review_id)
        if result is None:
            raise HTTPException(status_code=404, detail="review not found")
        return result.model_dump(by_alias=True, mode="json")

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app

app = create_app()
