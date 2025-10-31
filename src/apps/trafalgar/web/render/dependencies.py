"""Dependency helpers for the Trafalgar render API."""

from __future__ import annotations

import os
from datetime import timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Mapping

from fastapi import Body, Depends
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from apps.trafalgar.web.job_store import JobStore
from .schemas import RenderJobRequest

if TYPE_CHECKING:  # pragma: no cover - import for type checkers only
    from . import RenderSubmissionService


JOB_STORE_PATH_ENV = "TRAFALGAR_RENDER_JOBS_PATH"
JOB_HISTORY_LIMIT_ENV = "TRAFALGAR_RENDER_JOBS_HISTORY_LIMIT"
JOB_RETENTION_HOURS_ENV = "TRAFALGAR_RENDER_JOBS_RETENTION_HOURS"
JOB_STATUS_POLL_INTERVAL_ENV = "TRAFALGAR_RENDER_STATUS_POLL_INTERVAL"
JOB_STORE_PERSIST_THROTTLE_ENV = "TRAFALGAR_RENDER_STORE_PERSIST_INTERVAL"


def _initialise_render_service() -> "RenderSubmissionService":
    from . import JOB_EVENTS, RenderSubmissionService, logger

    store_path = os.environ.get(JOB_STORE_PATH_ENV)
    history_limit_value = os.environ.get(JOB_HISTORY_LIMIT_ENV)
    retention_hours_value = os.environ.get(JOB_RETENTION_HOURS_ENV)
    poll_interval_value = os.environ.get(JOB_STATUS_POLL_INTERVAL_ENV)
    persist_interval_value = os.environ.get(JOB_STORE_PERSIST_THROTTLE_ENV)

    retention: timedelta | None = None
    if retention_hours_value:
        try:
            hours = float(retention_hours_value)
        except ValueError:
            logger.warning(
                "render.job.retention.invalid",
                value=retention_hours_value,
                env=JOB_RETENTION_HOURS_ENV,
            )
        else:
            if hours <= 0:
                logger.warning(
                    "render.job.retention.ignored",
                    value=retention_hours_value,
                    env=JOB_RETENTION_HOURS_ENV,
                )
            else:
                retention = timedelta(hours=hours)

    job_store = JobStore(store_path, retention=retention) if store_path else None

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

    poll_interval_override: float | None = None
    if poll_interval_value is not None:
        try:
            poll_interval_override = float(poll_interval_value)
        except ValueError:
            logger.warning(
                "render.job.poll_interval.invalid",
                value=poll_interval_value,
                env=JOB_STATUS_POLL_INTERVAL_ENV,
            )
            poll_interval_override = None
        else:
            if poll_interval_override <= 0:
                logger.warning(
                    "render.job.poll_interval.disabled",
                    value=poll_interval_value,
                    env=JOB_STATUS_POLL_INTERVAL_ENV,
                )

    persist_interval_override: float | None = None
    if persist_interval_value is not None:
        try:
            persist_interval_override = float(persist_interval_value)
        except ValueError:
            logger.warning(
                "render.job.store_interval.invalid",
                value=persist_interval_value,
                env=JOB_STORE_PERSIST_THROTTLE_ENV,
            )
            persist_interval_override = None
        else:
            if persist_interval_override <= 0:
                logger.warning(
                    "render.job.store_interval.disabled",
                    value=persist_interval_value,
                    env=JOB_STORE_PERSIST_THROTTLE_ENV,
                )

    service = RenderSubmissionService(
        job_store=job_store,
        history_limit=history_limit,
        broadcaster=JOB_EVENTS,
        status_poll_interval=poll_interval_override,
        store_persist_interval=persist_interval_override,
    )

    RenderJobRequest.configure_farm_registry(service.adapter_keys)

    return service


@lru_cache
def get_render_service() -> (
    "RenderSubmissionService"
):  # pragma: no cover - runtime wiring
    return _initialise_render_service()


def parse_render_job_request(
    payload: Mapping[str, Any] = Body(...),
    service: "RenderSubmissionService" = Depends(get_render_service),
) -> RenderJobRequest:
    """FastAPI dependency that validates render submissions with registry context."""

    registry = service.adapter_keys()
    try:
        return RenderJobRequest.model_validate(
            payload, context={"farm_registry": registry}
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


async def start_render_status_poller() -> None:
    service = get_render_service()
    service.start_background_polling()


async def stop_render_status_poller() -> None:
    service = get_render_service()
    await service.stop_background_polling()


__all__ = [
    "JOB_STORE_PATH_ENV",
    "JOB_HISTORY_LIMIT_ENV",
    "JOB_RETENTION_HOURS_ENV",
    "JOB_STATUS_POLL_INTERVAL_ENV",
    "JOB_STORE_PERSIST_THROTTLE_ENV",
    "get_render_service",
    "parse_render_job_request",
    "start_render_status_poller",
    "stop_render_status_poller",
]
