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
