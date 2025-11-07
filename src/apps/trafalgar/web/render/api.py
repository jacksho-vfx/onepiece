"""Helper functions and middleware for the render API."""

from __future__ import annotations

from typing import Awaitable, Callable

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from apps.onepiece.render.submit import get_adapter_capabilities
from libraries.automation.render.base import (
    AdapterCapabilities,
    RenderSubmissionError,
)

from .schemas import (
    APIErrorDetail,
    APIErrorResponse,
    CancellationCapabilityDescriptor,
    ChunkingCapabilityDescriptor,
    FarmCapabilities,
    PriorityCapabilityDescriptor,
)

logger = structlog.get_logger(__name__)


def build_farm_capabilities(
    farm: str,
    capabilities: AdapterCapabilities | None,
) -> FarmCapabilities:
    """Translate adapter capability metadata into API descriptors."""

    if capabilities is None:
        try:
            raw_capabilities: AdapterCapabilities = get_adapter_capabilities(farm)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "render.farm.capabilities.unavailable",
                farm=farm,
                error=str(exc),
            )
            return FarmCapabilities()
    else:
        raw_capabilities = dict(capabilities)

    chunk_enabled = raw_capabilities.get("chunk_size_enabled", False)
    default_chunk = raw_capabilities.get("default_chunk_size")
    if not chunk_enabled:
        default_chunk = None

    return FarmCapabilities(
        priority=PriorityCapabilityDescriptor(
            default=raw_capabilities.get("default_priority", 50),
            minimum=raw_capabilities.get("priority_min"),
            maximum=raw_capabilities.get("priority_max"),
        ),
        chunking=ChunkingCapabilityDescriptor(
            enabled=chunk_enabled,
            minimum=raw_capabilities.get("chunk_size_min"),
            maximum=raw_capabilities.get("chunk_size_max"),
            default=default_chunk,
        ),
        cancellation=CancellationCapabilityDescriptor(
            supported=raw_capabilities.get("cancellation_supported", False),
        ),
    )


async def render_submission_error_handler(
    request: Request, exc: RenderSubmissionError
) -> JSONResponse:
    """Map adapter errors to standardised JSON responses."""

    status_code = exc.status_code or 400
    error_detail = APIErrorDetail(
        code=exc.code,
        message=str(exc),
        hint=exc.hint,
        context=exc.context or None,
    )
    log = logger.error if status_code >= 500 else logger.warning
    log(
        "render.api.error",
        code=error_detail.code,
        message=error_detail.message,
        hint=error_detail.hint,
        context=error_detail.context,
        status=status_code,
        path=str(request.url.path),
    )
    return JSONResponse(
        status_code=status_code,
        content=APIErrorResponse(error=error_detail).model_dump(exclude_none=True),
    )


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


__all__ = [
    "build_farm_capabilities",
    "log_requests",
    "render_submission_error_handler",
]
