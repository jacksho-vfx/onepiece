"""Streaming helpers for the Trafalgar render API."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, Mapping

from fastapi import Request

from apps.trafalgar.web.events import resolve_keepalive_interval
from apps.trafalgar.web.render.constants import JOB_EVENTS

from .dependencies import get_render_service

if TYPE_CHECKING:  # pragma: no cover - import for static analysis only
    from . import RenderSubmissionService


RENDER_SSE_KEEPALIVE_INTERVAL_ENV = "TRAFALGAR_RENDER_SSE_KEEPALIVE_INTERVAL"
_RENDER_SSE_STATE_ATTR = "render_sse_keepalive_interval"
_DEFAULT_SSE_KEEPALIVE_INTERVAL = 30.0


def _format_sse_chunk(event_name: str | None, payload: bytes) -> bytes:
    lines: list[bytes] = []
    if event_name:
        lines.append(b"event: " + event_name.encode("utf-8"))
    lines.append(b"data: " + payload)
    return b"\n".join(lines) + b"\n\n"


def _resolve_render_keepalive_interval(request: Request) -> float:
    return float(
        resolve_keepalive_interval(
            request,
            env_name=RENDER_SSE_KEEPALIVE_INTERVAL_ENV,
            state_attr=_RENDER_SSE_STATE_ATTR,
            log_key="render.sse.keepalive",
            default=_DEFAULT_SSE_KEEPALIVE_INTERVAL,
        )
    )


async def _render_jobs_snapshot(
    service: "RenderSubmissionService",
) -> list[dict[str, Any]]:
    jobs = await asyncio.to_thread(service.list_jobs)
    return [job.model_dump(mode="json") for job in jobs]


async def _job_event_stream(request: Request) -> AsyncGenerator[bytes, Any]:
    service = get_render_service()
    queue = await JOB_EVENTS.subscribe()
    try:
        jobs_snapshot = await _render_jobs_snapshot(service)
        snapshot_event = {"event": "jobs.snapshot", "jobs": jobs_snapshot}
        snapshot_payload = json.dumps(snapshot_event).encode("utf-8")
        yield _format_sse_chunk("jobs.snapshot", snapshot_payload)

        while True:
            try:
                interval = _resolve_render_keepalive_interval(request)
                event = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    break
                yield _format_sse_chunk(None, b"{}")
                continue
            payload = json.dumps(event).encode("utf-8")
            event_name = event.get("event") if isinstance(event, Mapping) else None
            chunk = _format_sse_chunk(
                event_name if isinstance(event_name, str) else None, payload
            )
            yield chunk
    finally:
        await JOB_EVENTS.unsubscribe(queue)


__all__ = [
    "RENDER_SSE_KEEPALIVE_INTERVAL_ENV",
    "_format_sse_chunk",
    "_resolve_render_keepalive_interval",
    "_render_jobs_snapshot",
    "_job_event_stream",
]
