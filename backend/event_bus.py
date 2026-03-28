import asyncio
import json
from collections import deque
from typing import AsyncGenerator

subscribers: set[asyncio.Queue] = set()
history: deque = deque(maxlen=1000)


def broadcast(event_type: str, data: dict):
    """Send an SSE event to all connected subscribers."""
    msg = {"type": event_type, **data}
    history.append(msg)
    for q in subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


async def subscribe() -> AsyncGenerator[str, None]:
    """Yields SSE-formatted strings for a connected client."""
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    subscribers.add(q)
    try:
        while True:
            msg = await q.get()
            yield f"data: {json.dumps(msg)}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        subscribers.discard(q)
