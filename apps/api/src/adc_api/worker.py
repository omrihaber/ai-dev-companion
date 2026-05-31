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
    result = await svc.run(
        review_id=review_id, language=language, code=code, on_progress=on_progress
    )
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
