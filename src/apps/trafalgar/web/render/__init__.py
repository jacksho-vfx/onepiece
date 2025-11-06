"""FastAPI application exposing render job submission endpoints."""

from __future__ import annotations

from fastapi import FastAPI

from apps.trafalgar.version import TRAFALGAR_VERSION
from libraries.automation.render.base import RenderSubmissionError

from . import routes
from .api import log_requests, render_submission_error_handler
from .dependencies import (
    JOB_HISTORY_LIMIT_ENV,
    JOB_RETENTION_HOURS_ENV,
    JOB_STATUS_POLL_INTERVAL_ENV,
    JOB_STORE_PATH_ENV,
    JOB_STORE_PERSIST_THROTTLE_ENV,
    get_render_service,
    parse_render_job_request,
    start_render_status_poller,
    stop_render_status_poller,
)
from .models import _JobRecord, _parse_timestamp, _serialise_datetime, _utcnow
from .schemas import (
    APIErrorDetail,
    APIErrorResponse,
    CancellationCapabilityDescriptor,
    ChunkingCapabilityDescriptor,
    DurationMetrics,
    FarmCapabilities,
    FarmInfo,
    FarmsResponse,
    JobsListResponse,
    PriorityCapabilityDescriptor,
    RenderAdapterAnalytics,
    RenderAnalyticsResponse,
    RenderJobMetadata,
    RenderJobRequest,
    RenderJobResponse,
    RenderStatusAnalytics,
    RenderWindowAnalytics,
)
from .services import (
    JOB_EVENTS,
    RenderSubmissionService,
    logger,
)
from .streaming import RENDER_SSE_KEEPALIVE_INTERVAL_ENV
from .security import (
    AuthenticatedPrincipal,
    ROLE_RENDER_MANAGE,
    ROLE_RENDER_READ,
    ROLE_RENDER_SUBMIT,
)

app = FastAPI(title="OnePiece Render Service", version=TRAFALGAR_VERSION)

app.add_event_handler("startup", start_render_status_poller)
app.add_event_handler("shutdown", stop_render_status_poller)
app.add_exception_handler(RenderSubmissionError, render_submission_error_handler)
app.middleware("http")(log_requests)
router = routes.router  # type: ignore[has-type]

app.include_router(router)  # type: ignore[has-type]

__all__ = [
    "APIErrorDetail",
    "APIErrorResponse",
    "AuthenticatedPrincipal",
    "CancellationCapabilityDescriptor",
    "ChunkingCapabilityDescriptor",
    "DurationMetrics",
    "FarmCapabilities",
    "FarmInfo",
    "FarmsResponse",
    "JOB_EVENTS",
    "JOB_HISTORY_LIMIT_ENV",
    "JOB_RETENTION_HOURS_ENV",
    "JOB_STATUS_POLL_INTERVAL_ENV",
    "JOB_STORE_PATH_ENV",
    "JOB_STORE_PERSIST_THROTTLE_ENV",
    "JobsListResponse",
    "RENDER_SSE_KEEPALIVE_INTERVAL_ENV",
    "ROLE_RENDER_MANAGE",
    "ROLE_RENDER_READ",
    "ROLE_RENDER_SUBMIT",
    "RenderAdapterAnalytics",
    "RenderAnalyticsResponse",
    "RenderJobMetadata",
    "RenderJobRequest",
    "RenderJobResponse",
    "RenderStatusAnalytics",
    "RenderSubmissionError",
    "RenderSubmissionService",
    "RenderWindowAnalytics",
    "PriorityCapabilityDescriptor",
    "_JobRecord",
    "_parse_timestamp",
    "_serialise_datetime",
    "_utcnow",
    "app",
    "get_render_service",
    "logger",
    "log_requests",
    "parse_render_job_request",
    "render_submission_error_handler",
    "router",
    "start_render_status_poller",
    "stop_render_status_poller",
]
