from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable

from adc_core.models import ReviewResult
from adc_core.sanitization import validate_submission

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.review_service import ReviewService
from adc_api.schemas import ProgressEvent

_TERMINAL = {"done", "failed"}


class JobManager:
    """In-memory job store + per-review async event bus (Inc 1).

    Swappable for arq+Redis in Inc 2+.
    """

    def __init__(self, agents_factory: Callable[[], list[SpecialistAgent]] = build_agents) -> None:
        self._agents_factory = agents_factory
        self._results: dict[str, ReviewResult] = {}
        self._queues: dict[str, asyncio.Queue[ProgressEvent | None]] = {}
        # Hold strong refs: the event loop only weakly references tasks, so a
        # fire-and-forget review could otherwise be garbage-collected mid-run.
        self._tasks: set[asyncio.Task[None]] = set()

    def create(self, *, language: str, code: str, max_bytes: int, max_lines: int) -> str:
        code = validate_submission(language, code, max_bytes=max_bytes, max_lines=max_lines)
        review_id = str(uuid.uuid4())
        self._results[review_id] = ReviewResult(id=review_id, language=language, model="pending")
        self._queues[review_id] = asyncio.Queue()
        task = asyncio.create_task(self._run(review_id, language, code))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return review_id

    async def _run(self, review_id: str, language: str, code: str) -> None:
        queue = self._queues[review_id]

        def on_progress(event: ProgressEvent) -> None:
            queue.put_nowait(event)

        svc = ReviewService(agents=self._agents_factory())
        result = await svc.run(
            review_id=review_id, language=language, code=code, on_progress=on_progress
        )
        self._results[review_id] = result
        queue.put_nowait(None)  # sentinel: stream complete

    async def stream(self, review_id: str) -> AsyncIterator[ProgressEvent]:
        queue = self._queues[review_id]
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event

    def get(self, review_id: str) -> ReviewResult | None:
        return self._results.get(review_id)

    def list_all(self) -> list[ReviewResult]:
        return list(self._results.values())
