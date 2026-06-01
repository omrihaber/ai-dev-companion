from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.corpus import CorpusStore
from adc_api.events import EventBus
from adc_api.repository import ReviewRepository
from adc_api.worker import run_review_core


class ReviewQueue(Protocol):
    async def enqueue(self, review_id: str, marked: list[str]) -> None: ...


class InlineReviewQueue:
    """Runs the review in-process (memory backend / tests / quick demo), fire-and-forget."""

    def __init__(
        self,
        repo: ReviewRepository,
        bus: EventBus,
        store: CorpusStore,
        agents_factory: Callable[[], list[SpecialistAgent]] = build_agents,
    ) -> None:
        self._repo = repo
        self._bus = bus
        self._store = store
        self._agents_factory = agents_factory
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, review_id: str, marked: list[str]) -> None:
        task = asyncio.create_task(
            run_review_core(
                review_id, marked, repo=self._repo, bus=self._bus, store=self._store,
                agents=self._agents_factory(),
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


class ArqReviewQueue:
    """Enqueues the `run_review` job onto arq/Redis (production)."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def enqueue(self, review_id: str, marked: list[str]) -> None:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        try:
            await pool.enqueue_job("run_review", review_id, marked)
        finally:
            await pool.aclose()
