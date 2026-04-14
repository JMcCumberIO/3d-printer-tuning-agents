import asyncio
import pytest
from server.sse import SSEBroker


async def test_publish_delivers_event_to_subscriber():
    broker = SSEBroker()
    async with broker.subscribe() as q:
        await broker.publish({"type": "test"})
        event = q.get_nowait()
    assert event == {"type": "test"}


async def test_publish_delivers_to_all_subscribers():
    broker = SSEBroker()
    async with broker.subscribe() as q1:
        async with broker.subscribe() as q2:
            await broker.publish({"type": "multi"})
            assert q1.get_nowait() == {"type": "multi"}
            assert q2.get_nowait() == {"type": "multi"}


async def test_publish_drops_frame_when_queue_full():
    broker = SSEBroker()
    async with broker.subscribe() as q:
        for i in range(10):
            await broker.publish({"n": i})
        # 11th publish must not raise or block
        await broker.publish({"n": 10})
        assert q.qsize() == 10  # still 10; 11th was dropped


async def test_subscribe_cleanup_removes_queue_on_exit():
    broker = SSEBroker()
    async with broker.subscribe():
        assert broker.subscriber_count() == 1
    assert broker.subscriber_count() == 0


async def test_publish_with_no_subscribers_is_noop():
    broker = SSEBroker()
    await broker.publish({"type": "empty"})  # must not raise
