from __future__ import annotations

import asyncio

from adc_api.agents import SpecialistAgent, build_agents
from adc_api.corpus import CorpusStore
from adc_api.events import EventBus, RedisEventBus
from adc_api.repository import ReviewRepository, SqlReviewRepository
from adc_api.review_service import ReviewService
from adc_api.schemas import ProgressEvent

_TERMINAL = {"done", "failed"}


async def run_review_core(
    review_id: str,
    marked: list[str],
    *,
    repo: ReviewRepository,
    bus: EventBus,
    store: CorpusStore,
    agents: list[SpecialistAgent],
) -> None:
    """Load the persisted corpus, run the two-tier review, stream non-terminal stages live, then
    save the final result and publish the terminal event LAST."""
    events: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()

    def on_progress(event: ProgressEvent) -> None:
        events.put_nowait(event)

    async def drain() -> None:
        while True:
            ev = await events.get()
            if ev is None:
                return
            if ev.stage not in _TERMINAL:
                await repo.set_status(review_id, ev.stage)
                await bus.publish(review_id, ev)

    drain_task = asyncio.create_task(drain())
    svc = ReviewService(agents=agents)
    result = await svc.run(
        review_id=review_id, files=store.list_files(review_id), marked=set(marked),
        on_progress=on_progress, work_dir=str(store.path(review_id)),
    )
    events.put_nowait(None)
    await drain_task

    await repo.save_result(result)
    await bus.publish(review_id, ProgressEvent(review_id=review_id, stage=result.status))


# ---- arq task + worker settings (production) ----

async def run_review(ctx: dict, review_id: str, marked: list[str]) -> None:
    await run_review_core(
        review_id, marked, repo=ctx["repo"], bus=ctx["bus"], store=ctx["store"],
        agents=build_agents(),
    )


async def _on_startup(ctx: dict) -> None:
    from adc_api.db.engine import make_engine, make_session_factory
    from adc_api.settings import settings

    ctx["repo"] = SqlReviewRepository(make_session_factory(make_engine(settings.database_url)))
    ctx["bus"] = RedisEventBus(settings.redis_url)
    ctx["store"] = CorpusStore(settings.work_root)


def _redis_settings():
    from arq.connections import RedisSettings

    from adc_api.settings import settings

    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    functions = [run_review]
    on_startup = _on_startup
    redis_settings = _redis_settings()
    max_tries = 1
