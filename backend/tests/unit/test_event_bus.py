"""Tests for event_bus.py"""

import asyncio
import pytest
from event_bus import broadcast, subscribe, subscribers, history


@pytest.fixture(autouse=True)
def cleanup():
    """Clear subscribers and history between tests."""
    subscribers.clear()
    history.clear()
    yield
    subscribers.clear()
    history.clear()


class TestBroadcast:
    def test_adds_to_history(self):
        broadcast("test_event", {"key": "value"})
        assert len(history) == 1
        assert history[0]["type"] == "test_event"
        assert history[0]["key"] == "value"

    def test_sends_to_subscribers(self):
        q = asyncio.Queue(maxsize=10)
        subscribers.add(q)
        broadcast("update", {"id": "1"})
        msg = q.get_nowait()
        assert msg["type"] == "update"
        assert msg["id"] == "1"

    def test_multiple_subscribers(self):
        q1 = asyncio.Queue(maxsize=10)
        q2 = asyncio.Queue(maxsize=10)
        subscribers.add(q1)
        subscribers.add(q2)
        broadcast("event", {})
        assert not q1.empty()
        assert not q2.empty()


class TestSubscribe:
    async def test_yields_messages(self):
        gen = subscribe()
        # Start the generator
        task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.01)
        broadcast("hello", {"data": "world"})
        result = await asyncio.wait_for(task, timeout=1.0)
        assert '"hello"' in result
        assert "data" in result
        # Cleanup
        await gen.aclose()
