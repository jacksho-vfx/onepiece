"""Async broadcast primitives and helpers for Trafalgar web services."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_KEEPALIVE_ENV_CACHE: dict[str, tuple[str | None, float | None]] = {}
_KEEPALIVE_STATE_CACHE: dict[tuple[int, str], tuple[Any, float | None]] = {}


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


def _parse_keepalive_value(
    raw_value: Any,
    *,
    log_key: str,
    source: str,
    context: dict[str, Any],
) -> float | None:
    """Coerce ``raw_value`` into a positive float or log and return ``None``."""

    try:
        interval = float(raw_value)
    except (TypeError, ValueError):
        logger.warning(f"{log_key}.{source}_invalid", value=raw_value, **context)
        return None

    if interval <= 0:
        logger.warning(f"{log_key}.{source}_ignored", value=raw_value, **context)
        return None

    return interval


def _keepalive_interval_from_state(app: Any, *, attr: str, log_key: str) -> float | None:
    """Return an override stored on ``app.state`` if available."""

    state = getattr(app, "state", None)
    if state is None or not hasattr(state, attr):
        _KEEPALIVE_STATE_CACHE.pop((id(app), attr), None)
        return None

    raw_value = getattr(state, attr)
    cache_key = (id(app), attr)
    cached = _KEEPALIVE_STATE_CACHE.get(cache_key)
    if cached and cached[0] == raw_value:
        return cached[1]

    if raw_value is None:
        interval = None
    else:
        interval = _parse_keepalive_value(
            raw_value, log_key=log_key, source="state", context={"attribute": attr}
        )

    _KEEPALIVE_STATE_CACHE[cache_key] = (raw_value, interval)
    return interval


def _keepalive_interval_from_env(*, env_name: str, log_key: str) -> float | None:
    """Return a cached override sourced from an environment variable."""

    raw_value = os.environ.get(env_name)
    cached = _KEEPALIVE_ENV_CACHE.get(env_name)
    if cached and cached[0] == raw_value:
        return cached[1]

    if raw_value is None:
        interval = None
    else:
        interval = _parse_keepalive_value(
            raw_value, log_key=log_key, source="env", context={"env": env_name}
        )

    _KEEPALIVE_ENV_CACHE[env_name] = (raw_value, interval)
    return interval


def resolve_keepalive_interval(
    request: Any,
    *,
    env_name: str,
    state_attr: str,
    log_key: str,
    default: float,
) -> float:
    """Resolve the keepalive interval for an SSE stream.

    The lookup order is:

    1. ``request.app.state`` attribute if present and valid.
    2. Environment variable referenced by ``env_name``.
    3. ``default`` when neither override is available.
    """

    app = getattr(request, "app", None)
    if app is not None:
        state_interval = _keepalive_interval_from_state(app, attr=state_attr, log_key=log_key)
        if state_interval is not None:
            return state_interval

    env_interval = _keepalive_interval_from_env(env_name=env_name, log_key=log_key)
    if env_interval is not None:
        return env_interval

    return default


def clear_keepalive_caches() -> None:
    """Reset cached keepalive values (useful for tests)."""

    _KEEPALIVE_ENV_CACHE.clear()
    _KEEPALIVE_STATE_CACHE.clear()
