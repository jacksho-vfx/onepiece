"""FastAPI application exposing render job submission endpoints."""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass
from functools import lru_cache
import asyncio
import json
from typing import Any, Awaitable, Callable, Mapping, Sequence

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.responses import Response
from starlette.websockets import WebSocketDisconnect

from apps.onepiece.render.submit import (
    DCC_CHOICES,
    FARM_ADAPTERS,
    _resolve_priority_and_chunk_size,
)
from apps.trafalgar.version import TRAFALGAR_VERSION
from libraries.render.base import RenderSubmissionError, SubmissionResult
from libraries.render.models import RenderAdapter

from apps.trafalgar.web.events import EventBroadcaster
from apps.trafalgar.web.job_store import JobStore

logger = structlog.get_logger(__name__)

FARM_DESCRIPTIONS: Mapping[str, str] = {
    "deadline": "Autodesk Deadline render manager (stub).",
    "tractor": "Pixar Tractor render farm (stub).",
    "opencue": "OpenCue render manager (stub).",
    "mock": "Mock render farm for testing and demos.",
}


class FarmInfo(BaseModel):
    """Metadata describing a render farm adapter."""

    name: str = Field(..., description="Adapter identifier used by the API and CLI.")
    description: str = Field(
        ..., description="Human readable description of the adapter."
    )


class FarmsResponse(BaseModel):
    """Response payload enumerating available render farm adapters."""

    farms: Sequence[FarmInfo]


class RenderJobRequest(BaseModel):
    """Request payload mirroring the CLI submission options."""

    dcc: str = Field(
        ..., description="Digital content creation package (e.g. maya, nuke)."
    )
    scene: str = Field(
        ..., description="Path to the scene file that should be rendered."
    )
    frames: str = Field(
        "1-100",
        description="Frame range to render, supporting Deadline style notation (e.g. 1-100x2).",
    )
    output: str = Field(..., description="Directory for rendered frames.")
    farm: str = Field(
        "mock",
        description="Render farm to submit to (see /farms for the available adapters).",
    )
    priority: int | None = Field(
        None,
        ge=0,
        description="Render job priority communicated to the adapter (defaults to adapter metadata).",
    )
    chunk_size: int | None = Field(
        None,
        ge=1,
        description="Frames per chunk to dispatch when supported by the adapter.",
    )
    user: str | None = Field(
        None,
        description="Submitting user; defaults to the service account if omitted.",
    )

    @field_validator("dcc")
    @classmethod
    def _normalise_dcc(cls, value: str) -> str:
        text = value.strip().lower()
        if text not in DCC_CHOICES:
            raise ValueError(
                f"Unsupported DCC '{value}'. Choose one of: {', '.join(sorted(DCC_CHOICES))}."
            )
        return text

    @field_validator("farm")
    @classmethod
    def _normalise_farm(cls, value: str) -> str:
        text = value.strip().lower()
        if text not in FARM_ADAPTERS:
            raise ValueError(
                f"Unknown farm '{value}'. Choose one of: {', '.join(sorted(FARM_ADAPTERS))}."
            )
        return text

    @field_validator("scene", "output", "frames", "user", mode="before")
    @classmethod
    def _strip_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("Value cannot be empty.")
        return text


class RenderJobResponse(BaseModel):
    """Response payload describing the outcome of a render submission."""

    job_id: str = Field(
        ..., description="Identifier returned by the render farm (if any)."
    )
    status: str = Field(
        ..., description="Submission status reported by the render farm."
    )
    farm_type: str = Field(
        ..., description="Render farm adapter that processed the submission."
    )
    message: str | None = Field(
        None,
        description="Optional detail returned by the adapter (for example not implemented notices).",
    )


class RenderJobMetadata(BaseModel):
    """Structured metadata about a submitted render job."""

    job_id: str = Field(..., description="Job identifier returned by the adapter.")
    farm: str = Field(..., description="Registered adapter key handling the job.")
    farm_type: str = Field(..., description="Adapter type reported by the farm.")
    status: str = Field(..., description="Current status reported for the job.")
    message: str | None = Field(
        None, description="Optional status message provided by the adapter."
    )
    request: RenderJobRequest = Field(
        ..., description="Original submission payload for the job."
    )


class JobsListResponse(BaseModel):
    """Envelope returned when listing render jobs."""

    jobs: Sequence[RenderJobMetadata]


@dataclass
class _JobRecord:
    """Internal storage representation for submitted render jobs."""

    job_id: str
    farm: str
    farm_type: str
    status: str
    message: str | None
    request: RenderJobRequest

    def snapshot(self) -> RenderJobMetadata:
        return RenderJobMetadata(
            job_id=self.job_id,
            farm=self.farm,
            farm_type=self.farm_type,
            status=self.status,
            message=self.message,
            request=self.request.model_copy(deep=True),
        )

    def to_storage(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "farm": self.farm,
            "farm_type": self.farm_type,
            "status": self.status,
            "message": self.message,
            "request": self.request.model_dump(),
        }

    @classmethod
    def from_storage(cls, payload: Mapping[str, Any]) -> "_JobRecord":
        return cls(
            job_id=str(payload["job_id"]),
            farm=str(payload["farm"]),
            farm_type=str(payload.get("farm_type", payload["farm"])),
            status=str(payload.get("status", "unknown")),
            message=payload.get("message"),
            request=RenderJobRequest(**payload["request"]),
        )


JOB_STORE_PATH_ENV = "TRAFALGAR_RENDER_JOBS_PATH"
JOB_HISTORY_LIMIT_ENV = "TRAFALGAR_RENDER_JOBS_HISTORY_LIMIT"


class RenderSubmissionService:
    """Submit render jobs using the shared adapter registry."""

    def __init__(
        self,
        adapters: Mapping[str, RenderAdapter] | None = None,
        *,
        job_store: JobStore | None = None,
        history_limit: int | None = None,
        broadcaster: EventBroadcaster | None = None,
    ) -> None:
        self._adapters = dict(adapters or FARM_ADAPTERS)
        self._jobs: dict[str, _JobRecord] = {}
        self._store = job_store
        self._history_limit = (
            history_limit if history_limit and history_limit > 0 else None
        )
        self._events = broadcaster
        self._load_jobs()

    def list_farms(self) -> list[FarmInfo]:
        entries: list[FarmInfo] = []
        for name in sorted(self._adapters):
            description = FARM_DESCRIPTIONS.get(
                name, f"Render farm adapter registered as '{name}'."
            )
            entries.append(FarmInfo(name=name, description=description))
        return entries

    def submit_job(self, request: RenderJobRequest) -> SubmissionResult:
        adapter = self._adapters.get(request.farm)
        if adapter is None:
            raise RenderSubmissionError(f"Unknown render farm '{request.farm}'.")
        resolved_user = request.user or getpass.getuser()
        resolved_priority, resolved_chunk, _ = _resolve_priority_and_chunk_size(
            farm=request.farm,
            priority=request.priority,
            chunk_size=request.chunk_size,
        )
        result = adapter(
            scene=request.scene,
            frames=request.frames,
            output=request.output,
            dcc=request.dcc,
            priority=resolved_priority,
            user=resolved_user,
            chunk_size=resolved_chunk,
        )
        job_id = result.get("job_id", "")
        stored_request = request.model_copy(
            update={"priority": resolved_priority, "chunk_size": resolved_chunk},
            deep=True,
        )
        record = _JobRecord(
            job_id=job_id,
            farm=request.farm,
            farm_type=result.get("farm_type", request.farm),
            status=result.get("status", "unknown"),
            message=result.get("message"),
            request=stored_request,
        )
        if job_id:
            self._jobs[job_id] = record
            self._enforce_history_limit()
            self._persist_jobs()
            self._emit_event("job.created", record)
        return result

    def list_jobs(self) -> list[RenderJobMetadata]:
        jobs: list[RenderJobMetadata] = []
        dirty = False
        for record in self._jobs.values():
            dirty = self._refresh_job(record) or dirty
            jobs.append(record.snapshot())
        if dirty:
            self._persist_jobs()
        return jobs

    def get_job(self, job_id: str) -> RenderJobMetadata:
        record = self._jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if self._refresh_job(record):
            self._persist_jobs()
        return record.snapshot()

    def cancel_job(self, job_id: str) -> RenderJobMetadata:
        record = self._jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        adapter = self._adapters.get(record.farm)
        if adapter is None:
            raise RenderSubmissionError(
                f"Unknown render farm '{record.farm}' for job '{job_id}'."
            )
        cancel = getattr(adapter, "cancel_job", None)
        if not callable(cancel):
            raise RenderSubmissionError(
                f"Render farm '{record.farm}' does not support job cancellation."
            )
        try:
            result = cancel(job_id)
        except RenderSubmissionError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("render.job.cancel.error", job_id=job_id, farm=record.farm)
            raise RenderSubmissionError(
                f"Failed to cancel job '{job_id}' on farm '{record.farm}'."
            ) from exc
        if self._update_record_from_result(record, result):
            self._persist_jobs()
        return record.snapshot()

    def _refresh_job(self, record: _JobRecord) -> bool:
        adapter = self._adapters.get(record.farm)
        if adapter is None:
            return False
        status_lookup = getattr(adapter, "get_job_status", None)
        if not callable(status_lookup):
            return False
        try:
            result = status_lookup(record.job_id)
        except RenderSubmissionError as exc:
            logger.warning(
                "render.job.status.failed",
                job_id=record.job_id,
                farm=record.farm,
                error=str(exc),
            )
            return False
        except Exception:  # pragma: no cover - defensive guard
            logger.exception(
                "render.job.status.error", job_id=record.job_id, farm=record.farm
            )
            return False
        return self._update_record_from_result(record, result)

    def _update_record_from_result(
        self, record: _JobRecord, result: SubmissionResult
    ) -> bool:
        changed = False
        status = result.get("status")
        if status and status != record.status:
            record.status = status
            changed = True
        if "message" in result and result.get("message") != record.message:
            record.message = result.get("message")
            changed = True
        farm_type = result.get("farm_type")
        if farm_type and farm_type != record.farm_type:
            record.farm_type = farm_type
            changed = True
        if changed:
            self._emit_event("job.updated", record)
        return changed

    def _load_jobs(self) -> None:
        if not self._store:
            return
        for record in self._store.load():
            self._jobs[record.job_id] = record
        previous_count = len(self._jobs)
        self._enforce_history_limit()
        if self._history_limit is not None and len(self._jobs) < previous_count:
            self._persist_jobs()

    def _persist_jobs(self) -> None:
        if not self._store:
            return
        self._store.save(self._jobs.values())

    def _enforce_history_limit(self) -> None:
        if self._history_limit is None:
            return
        while len(self._jobs) > self._history_limit:
            oldest_key = next(iter(self._jobs))
            record = self._jobs.pop(oldest_key, None)
            if record is not None:
                self._emit_event(
                    "job.removed",
                    record,
                    payload_override={"job": {"job_id": record.job_id}},
                )

    def _emit_event(
        self,
        event: str,
        record: _JobRecord,
        *,
        payload_override: Mapping[str, Any] | None = None,
    ) -> None:
        if not self._events:
            return
        payload = {"event": event, "job": record.snapshot().model_dump()}
        if payload_override:
            payload.update(payload_override)
        self._events.publish(payload)


JOB_EVENTS = EventBroadcaster(max_buffer=64)


@lru_cache
def get_render_service() -> (
    RenderSubmissionService
):  # pragma: no cover - runtime wiring
    store_path = os.environ.get(JOB_STORE_PATH_ENV)
    history_limit_value = os.environ.get(JOB_HISTORY_LIMIT_ENV)

    job_store = JobStore(store_path) if store_path else None

    history_limit = None
    if history_limit_value:
        try:
            history_limit = int(history_limit_value)
        except ValueError:
            logger.warning(
                "render.job.history_limit.invalid",
                value=history_limit_value,
                env=JOB_HISTORY_LIMIT_ENV,
            )

    return RenderSubmissionService(
        job_store=job_store,
        history_limit=history_limit,
        broadcaster=JOB_EVENTS,
    )


app = FastAPI(title="OnePiece Render Service", version=TRAFALGAR_VERSION)


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    logger.info(
        "render.api.request.start", method=request.method, path=request.url.path
    )
    response = await call_next(request)
    logger.info(
        "render.api.request.complete",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    return response


@app.get("/")
def root() -> Mapping[str, str]:
    return {"message": "OnePiece Render API is running"}


@app.get("/health")
def health() -> Mapping[str, str]:
    return {"status": "ok"}


@app.get("/farms", response_model=FarmsResponse)
def farms(
    service: RenderSubmissionService = Depends(get_render_service),
) -> FarmsResponse:
    entries = service.list_farms()
    return FarmsResponse(farms=entries)


@app.post("/jobs")
async def create_job(
    request: RenderJobRequest,
    service: RenderSubmissionService = Depends(get_render_service),
) -> JSONResponse:
    logger.info(
        "render.api.submit.start",
        dcc=request.dcc,
        scene=request.scene,
        frames=request.frames,
        output=request.output,
        farm=request.farm,
        priority=request.priority,
        user=request.user,
    )
    try:
        result = service.submit_job(request)
    except RenderSubmissionError as exc:
        logger.warning(
            "render.api.submit.failed",
            farm=request.farm,
            scene=request.scene,
            error=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception(
            "render.api.submit.error",
            farm=request.farm,
            scene=request.scene,
        )
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while submitting render job.",
        ) from exc

    payload = RenderJobResponse(
        job_id=result.get("job_id", ""),
        status=result.get("status", "unknown"),
        farm_type=result.get("farm_type", request.farm),
        message=result.get("message"),
    )

    status_code = 201
    if payload.status == "not_implemented":
        status_code = 501

    logger.info(
        "render.api.submit.complete",
        farm=payload.farm_type,
        status=payload.status,
        job_id=payload.job_id,
    )

    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.get("/jobs", response_model=JobsListResponse)
def list_jobs(
    service: RenderSubmissionService = Depends(get_render_service),
) -> JobsListResponse:
    jobs = service.list_jobs()
    return JobsListResponse(jobs=jobs)


async def _job_event_stream(request: Request):
    queue = await JOB_EVENTS.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    break
                yield b"data: {}\n\n"
                continue
            payload = json.dumps(event).encode("utf-8")
            yield b"data: " + payload + b"\n\n"
    finally:
        await JOB_EVENTS.unsubscribe(queue)


@app.get("/jobs/stream")
async def stream_jobs(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _job_event_stream(request), media_type="text/event-stream"
    )


@app.websocket("/jobs/ws")
async def jobs_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = await JOB_EVENTS.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await JOB_EVENTS.unsubscribe(queue)


@app.get("/jobs/{job_id}", response_model=RenderJobMetadata)
def get_job(
    job_id: str, service: RenderSubmissionService = Depends(get_render_service)
) -> RenderJobMetadata:
    try:
        return service.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


@app.delete("/jobs/{job_id}", response_model=RenderJobMetadata)
def cancel_job(
    job_id: str, service: RenderSubmissionService = Depends(get_render_service)
) -> RenderJobMetadata:
    try:
        return service.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    except RenderSubmissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


