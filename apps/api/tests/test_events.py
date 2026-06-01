import pytest
from adc_api.events import InMemoryEventBus
from adc_api.schemas import ProgressEvent


@pytest.mark.asyncio
async def test_subscribe_receives_published_until_terminal():
    bus = InMemoryEventBus()
    agen = await bus.subscribe("r1")
    await bus.publish("r1", ProgressEvent(review_id="r1", stage="analyzing"))
    await bus.publish("r1", ProgressEvent(review_id="r1", stage="done"))
    seen = [ev.stage async for ev in agen]
    assert seen == ["analyzing", "done"]  # stops after terminal


@pytest.mark.asyncio
async def test_publish_with_no_subscriber_is_noop():
    bus = InMemoryEventBus()
    await bus.publish("nobody", ProgressEvent(review_id="nobody", stage="done"))  # must not raise
