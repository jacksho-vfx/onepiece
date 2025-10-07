"""Async broadcast primitives for Trafalgar web services."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class EventBroadcaster:
    """Publish state updates to multiple subscribers with backpressure handling."""

    def __init__(self, max_buffer: int = 32) -> None:
        self._max_buffer = max_buffer
        self._subscribers: set[asyncio.Queue[Any]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[Any]:
        """Register a new subscriber and return its queue."""

        queue: asyncio.Queue[Any] = asyncio.Queue(self._max_buffer)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[Any]) -> None:
        """Remove a subscriber queue from the broadcast set."""

        async with self._lock:
            self._subscribers.discard(queue)

    async def iter(self) -> AsyncIterator[Any]:
        """Yield events for the lifetime of the subscription."""

        queue = await self.subscribe()
        try:
            while True:
                yield await queue.get()
        finally:
            await self.unsubscribe(queue)

    def publish(self, payload: Any) -> None:
        """Schedule an event for delivery to all subscribers."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._publish(payload))
        else:
            loop.create_task(self._publish(payload))

    async def _publish(self, payload: Any) -> None:
        """Dispatch payload to all subscribers respecting backpressure."""

        async with self._lock:
            subscribers = list(self._subscribers)

        if not subscribers:
            return

        to_remove: list[asyncio.Queue[Any]] = []
        for queue in subscribers:
            if not self._offer(queue, payload):
                to_remove.append(queue)

        if to_remove:
            async with self._lock:
                for queue in to_remove:
                    removed = queue in self._subscribers
                    self._subscribers.discard(queue)
                    if removed:
                        logger.warning(
                            "trafalgar.events.dropped_subscriber", queue_id=id(queue)
                        )

    def _offer(self, queue: asyncio.Queue[Any], payload: Any) -> bool:
        """Attempt to enqueue ``payload`` without blocking.

        Returns ``True`` if the payload was enqueued or ``False`` when the
        subscriber was dropped because it could not keep up with the stream.
        """

        try:
            queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            # Drop the oldest item and retry once. If the queue is still full the
            # consumer is too slow and the subscription is removed to avoid
            # accumulating unbounded work.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - defensive guard
                pass
            try:
                queue.put_nowait(payload)
                logger.warning(
                    "trafalgar.events.backpressure", queue_id=id(queue), action="trim"
                )
                return True
            except asyncio.QueueFull:
                logger.warning(
                    "trafalgar.events.backpressure", queue_id=id(queue), action="drop"
                )
                return False
