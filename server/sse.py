import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class SSEBroker:
    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._queues.append(q)
        try:
            yield q
        finally:
            self._queues.remove(q)

    async def publish(self, event: dict) -> None:
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow client — drop frame, never block

    def subscriber_count(self) -> int:
        return len(self._queues)
