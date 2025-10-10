"""FastAPI application exposing ingest run summaries for Trafalgar."""

import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    Mapping,
    Sequence,
    cast,
)

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response
from starlette.websockets import WebSocketDisconnect

from apps.trafalgar.version import TRAFALGAR_VERSION
from apps.trafalgar.web.events import EventBroadcaster, resolve_keepalive_interval
from apps.trafalgar.web.security import (
    AuthenticatedPrincipal,
    ROLE_INGEST_READ,
    create_protected_router,
    require_roles,
)
from libraries.ingest.registry import IngestRunRecord, IngestRunRegistry
from libraries.ingest.service import IngestReport, IngestedMedia

logger = structlog.get_logger(__name__)

INGEST_SSE_KEEPALIVE_INTERVAL_ENV = "TRAFALGAR_INGEST_SSE_KEEPALIVE_INTERVAL"
_INGEST_SSE_STATE_ATTR = "ingest_sse_keepalive_interval"
_DEFAULT_SSE_KEEPALIVE_INTERVAL = 30.0


def _serialise_media(media: IngestedMedia) -> Mapping[str, Any]:
    return {
        "path": str(media.path),
        "bucket": media.bucket,
        "key": media.key,
        "media_info": asdict(media.media_info),
    }


def _serialise_invalid(entries: Iterable[tuple[Any, str]]) -> list[Mapping[str, Any]]:
    return [{"path": str(path), "reason": reason} for path, reason in entries]


def _serialise_report(report: IngestReport) -> Mapping[str, Any]:
    return {
        "processed": [_serialise_media(media) for media in report.processed],
        "invalid": _serialise_invalid(report.invalid),
        "processed_count": report.processed_count,
        "invalid_count": report.invalid_count,
    }


def _serialise_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialise_run(record: IngestRunRecord) -> Mapping[str, Any]:
    return {
        "id": record.run_id,
        "started_at": _serialise_datetime(record.started_at),
        "completed_at": _serialise_datetime(record.completed_at),
        "status": "completed" if record.completed_at else "running",
        "report": _serialise_report(record.report),
    }


class IngestRunProvider:
    """Provide ingest run metadata by consulting the shared registry."""

    def __init__(self, registry: IngestRunRegistry | None = None) -> None:
        self._registry = registry or IngestRunRegistry()

    def _cached_runs(self, *, refresh: bool = False) -> list[IngestRunRecord]:
        return cast(
            list[IngestRunRecord], self._registry.load_all(force_refresh=refresh)
        )

    def load_recent_runs(self, limit: int | None = None) -> Sequence[IngestRunRecord]:
        records = self._cached_runs()
        records.sort(
            key=lambda record: record.started_at or datetime.min,
            reverse=True,
        )
        if limit is None:
            return records
        return records[:limit]

    def get_run(self, run_id: str) -> IngestRunRecord | None:
        for record in self._cached_runs():
            if record.run_id == run_id:
                return record
        return None


class IngestRunService:
    """Transform ingest run records into API-friendly payloads."""

    def __init__(
        self,
        provider: IngestRunProvider | None = None,
        *,
        serializer: Callable[[IngestRunRecord], Mapping[str, Any]] | None = None,
        broadcaster: EventBroadcaster | None = None,
    ) -> None:
        self._provider = provider or IngestRunProvider()
        self._serialize = serializer or _serialise_run
        self._events = broadcaster
        self._snapshots: dict[str, str] = {}

    def list_runs(self, limit: int) -> list[Mapping[str, Any]]:
        records = self._provider.load_recent_runs(limit)
        payloads = [self._serialize(record) for record in records]
        self._sync_events(payloads)
        return payloads

    def get_run(self, run_id: str) -> Mapping[str, Any]:
        record = self._provider.get_run(run_id)
        if record is None:
            raise KeyError(run_id)
        payload = self._serialize(record)
        self._track_run(payload)
        return payload

    def _track_run(self, payload: Mapping[str, Any]) -> None:
        if not self._events:
            return
        run_id = str(payload.get("id", ""))
        if not run_id:
            return
        signature = json.dumps(payload, sort_keys=True)
        previous = self._snapshots.get(run_id)
        if previous == signature:
            return
        self._snapshots[run_id] = signature
        event = "run.updated" if previous is not None else "run.created"
        self._events.publish({"event": event, "run": payload})

    def _sync_events(self, payloads: Sequence[Mapping[str, Any]]) -> None:
        if not self._events:
            return
        active_ids: set[str] = set()
        for payload in payloads:
            run_id = str(payload.get("id", ""))
            if not run_id:
                continue
            active_ids.add(run_id)
            self._track_run(payload)
        removed = set(self._snapshots) - active_ids
        for run_id in removed:
            self._snapshots.pop(run_id, None)
            self._events.publish({"event": "run.removed", "run": {"id": run_id}})


INGEST_EVENTS = EventBroadcaster(max_buffer=64)


def get_ingest_run_service() -> IngestRunService:  # pragma: no cover - runtime wiring
    return IngestRunService(broadcaster=INGEST_EVENTS)


app = FastAPI(title="OnePiece Ingest Runs", version=TRAFALGAR_VERSION)
router = create_protected_router()


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    logger.info("ingest.request.start", method=request.method, path=request.url.path)
    response = await call_next(request)
    logger.info(
        "ingest.request.complete",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    return response


@router.get("/")  # type: ignore[misc]
def root(
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_INGEST_READ)),
) -> dict[str, str]:
    return {"message": "OnePiece Ingest API is running"}


@router.get("/runs")  # type: ignore[misc]
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    service: IngestRunService = Depends(get_ingest_run_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_INGEST_READ)),
) -> JSONResponse:
    payload = service.list_runs(limit)
    return JSONResponse(content=payload)


def _resolve_ingest_keepalive_interval(request: Request) -> float:
    return resolve_keepalive_interval(
        request,
        env_name=INGEST_SSE_KEEPALIVE_INTERVAL_ENV,
        state_attr=_INGEST_SSE_STATE_ATTR,
        log_key="ingest.sse.keepalive",
        default=_DEFAULT_SSE_KEEPALIVE_INTERVAL,
    )


async def _ingest_event_stream(
    request: Request,
) -> AsyncGenerator[bytes, Any]:
    queue = await INGEST_EVENTS.subscribe()
    try:
        while True:
            try:
                interval = _resolve_ingest_keepalive_interval(request)
                event = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    break
                yield b"data: {}\n\n"
                continue
            payload = json.dumps(event).encode("utf-8")
            yield b"data: " + payload + b"\n\n"
    finally:
        await INGEST_EVENTS.unsubscribe(queue)


@router.get("/runs/stream")  # type: ignore[misc]
async def stream_runs(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_INGEST_READ)),
) -> StreamingResponse:
    return StreamingResponse(
        _ingest_event_stream(request), media_type="text/event-stream"
    )


@router.websocket("/runs/ws")  # type: ignore[misc]
async def runs_websocket(
    websocket: WebSocket,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_INGEST_READ)),
) -> None:
    await websocket.accept()
    queue = await INGEST_EVENTS.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await INGEST_EVENTS.unsubscribe(queue)


@router.get("/runs/{run_id}")  # type: ignore[misc]
async def get_run(
    run_id: str,
    service: IngestRunService = Depends(get_ingest_run_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_INGEST_READ)),
) -> JSONResponse:
    try:
        payload = service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return JSONResponse(content=payload)


@router.get("/health")  # type: ignore[misc]
def health_check(
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_INGEST_READ)),
) -> Dict[str, str]:
    return {"status": "ok"}


app.include_router(router)
