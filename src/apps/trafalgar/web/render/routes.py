"""HTTP routes for the Trafalgar render API."""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import Depends, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.websockets import WebSocketDisconnect

from apps.trafalgar.web.security import (
    ROLE_RENDER_MANAGE,
    ROLE_RENDER_READ,
    ROLE_RENDER_SUBMIT,
    AuthenticatedPrincipal,
    create_protected_router,
    require_roles,
)
from libraries.automation.render.base import RenderSubmissionError

from .api import render_submission_error_handler
from .constants import JOB_EVENTS
from .dependencies import get_render_service, parse_render_job_request
from .schemas import (
    FarmsResponse,
    JobsListResponse,
    RenderAnalyticsResponse,
    RenderJobMetadata,
    RenderJobRequest,
    RenderJobResponse,
)
from .services import RenderSubmissionService, logger
from .streaming import _job_event_stream, _render_jobs_snapshot

router = create_protected_router()


@router.get("/")  # type: ignore[misc]
def root(
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> Mapping[str, str]:
    return {"message": "OnePiece Render API is running"}


@router.get("/health")  # type: ignore[misc]
def health(
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> Mapping[str, Any]:
    analytics = service.get_render_analytics()
    status_summary = {
        name: {
            "count": metrics.count,
            "active": metrics.active,
            "average_duration_seconds": metrics.durations.average_seconds,
        }
        for name, metrics in analytics.statuses.items()
    }
    recent_submissions = {
        window: window_metrics.total_jobs
        for window, window_metrics in analytics.submission_windows.items()
    }
    active_jobs = sum(metric.active for metric in analytics.statuses.values())
    return {
        "status": "ok",
        "render_history": service.get_metrics(),
        "render_summary": {
            "total_jobs": analytics.total_jobs,
            "active_jobs": active_jobs,
            "by_status": status_summary,
            "submission_windows": recent_submissions,
        },
    }


@router.get("/farms", response_model=FarmsResponse)  # type: ignore[misc]
def farms(
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> FarmsResponse:
    entries = service.list_farms()
    return FarmsResponse(farms=entries)


@router.post("/jobs")  # type: ignore[misc]
async def create_job(
    http_request: Request,
    job_request: RenderJobRequest = Depends(parse_render_job_request),
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_SUBMIT)),
) -> JSONResponse:
    logger.info(
        "render.api.submit.start",
        dcc=job_request.dcc,
        scene=job_request.scene,
        frames=job_request.frames,
        output=job_request.output,
        farm=job_request.farm,
        priority=job_request.priority,
        user=job_request.user,
    )
    try:
        result = service.submit_job(job_request)
    except RenderSubmissionError as exc:
        return await render_submission_error_handler(http_request, exc)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception(
            "render.api.submit.error",
            farm=job_request.farm,
            scene=job_request.scene,
        )
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while submitting render job.",
        ) from exc

    payload = RenderJobResponse(
        job_id=result.get("job_id", ""),
        status=result.get("status", "unknown"),
        farm_type=result.get("farm_type", job_request.farm),
        message=result.get("message"),
    )

    logger.info(
        "render.api.submit.complete",
        job_id=payload.job_id,
        status=payload.status,
        farm_type=payload.farm_type,
    )
    return JSONResponse(payload.model_dump(exclude_none=True), status_code=201)


@router.get("/jobs", response_model=JobsListResponse)  # type: ignore[misc]
def list_jobs(
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
    limit: int | None = Query(
        None,
        gt=0,
        description="Maximum number of jobs to return.",
    ),
    status: list[str] | None = Query(
        None,
        description="Filter by one or more job status values.",
    ),
    farm: list[str] | None = Query(
        None,
        description="Filter by one or more farm identifiers.",
    ),
) -> JobsListResponse:
    jobs = service.list_jobs(limit=limit, status=status, farm=farm)
    return JobsListResponse(jobs=jobs)


@router.get("/jobs/metrics", response_model=RenderAnalyticsResponse)  # type: ignore[misc]
def job_metrics(
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> RenderAnalyticsResponse:
    return service.get_render_analytics()


@router.get("/jobs/stream")  # type: ignore[misc]
async def stream_jobs(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> StreamingResponse:
    return StreamingResponse(_job_event_stream(request), media_type="text/event-stream")


@router.websocket("/jobs/ws")  # type: ignore[misc]
async def jobs_websocket(
    websocket: WebSocket,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
    service: RenderSubmissionService = Depends(get_render_service),
) -> None:
    await websocket.accept()
    queue = await JOB_EVENTS.subscribe()
    try:
        jobs_snapshot = await _render_jobs_snapshot(service)
        handshake: dict[str, Any] = {
            "type": "connected",
            "snapshot": {"event": "jobs.snapshot", "jobs": jobs_snapshot},
        }
        await websocket.send_json(handshake)

        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await JOB_EVENTS.unsubscribe(queue)


@router.get("/jobs/{job_id}", response_model=RenderJobMetadata)  # type: ignore[misc]
def get_job(
    job_id: str,
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> RenderJobMetadata:
    try:
        return service.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


@router.delete("/jobs/{job_id}", response_model=RenderJobMetadata)  # type: ignore[misc]
def cancel_job(
    job_id: str,
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_MANAGE)),
) -> RenderJobMetadata:
    try:
        return service.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


__all__ = ["router"]
