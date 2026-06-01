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
