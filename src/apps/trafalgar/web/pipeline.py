"""FastAPI application exposing the pipeline orchestrator."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, Annotated, AsyncIterator, Mapping, Sequence

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.onepiece.config import load_profile
from apps.trafalgar.pipeline import (
    configure_orchestrator_from_profile,
    get_pipeline_orchestrator,
    pipeline_definition_from_profile_entry,
)
from apps.trafalgar.pipeline_manifest import translate_pipeline_manifest
from apps.trafalgar.version import TRAFALGAR_VERSION
from .security import (
    AuthenticatedPrincipal,
    ROLE_PIPELINE_READ,
    ROLE_PIPELINE_RUN,
    ROLE_PIPELINE_MANAGE,
    create_protected_router,
    require_roles,
)


class PipelineDefinitionSubmission(BaseModel):
    """Request payload describing a pipeline definition."""

    _ALLOWED_EXTRA_FIELDS = frozenset({"summary", "version"})

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    display_name: str | None = Field(default=None, alias="display_name")
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]] | None = None
    triggers: list[dict[str, Any]] | None = None

    @field_validator("steps", "triggers", mode="before")
    @classmethod
    def _ensure_sequence(cls, value: Any) -> list[dict[str, Any]] | None:
        if value is None:
            return None
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [dict(step) if isinstance(step, Mapping) else step for step in value]
        msg = "must be supplied as a sequence"
        raise TypeError(msg)

    @model_validator(mode="after")
    def _validate_manifest_shape(self) -> "PipelineDefinitionSubmission":
        if not self.steps and not self.triggers:
            msg = "pipeline definitions require 'steps' or 'triggers'"
            raise ValueError(msg)
        return self

    def unexpected_fields(self) -> list[str]:
        extras = set(self.model_extra or {})
        unexpected = sorted(extras - self._ALLOWED_EXTRA_FIELDS)
        return unexpected

    def translator_overrides(self) -> dict[str, Any]:
        if not self.model_extra:
            return {}
        return {
            key: value
            for key, value in self.model_extra.items()
            if key in self._ALLOWED_EXTRA_FIELDS and value is not None
        }


class PipelineRunSubmission(BaseModel):
    """Request payload used when triggering a pipeline run."""

    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters", mode="before")
    @classmethod
    def _validate_parameters(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {str(key): val for key, val in value.items()}
        msg = "parameters must be a mapping"
        raise TypeError(msg)


class PipelinePruneRequest(BaseModel):
    """Optional overrides supplied when pruning pipeline history."""

    max_age_hours: float | None = Field(default=None, ge=0, alias="max_age_hours")
    max_runs: int | None = Field(default=None, ge=0, alias="max_runs")


app = FastAPI(title="OnePiece Pipeline API", version=TRAFALGAR_VERSION)
router = create_protected_router()


@app.on_event("startup")
def _register_profile_pipelines() -> None:
    context = load_profile()
    configure_orchestrator_from_profile(
        context, storage_config=context.pipeline_storage
    )


@router.get("/")
def root(
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> dict[str, str]:
    """Return a simple payload confirming the service is available."""

    return {"message": "OnePiece Pipeline API is running"}


def _definition_from_submission(
    submission: PipelineDefinitionSubmission,
) -> Any:
    unexpected = submission.unexpected_fields()
    if unexpected:
        detail = f"Unexpected fields: {', '.join(unexpected)}"
        raise HTTPException(status_code=400, detail=detail)
    try:
        payload = submission.model_dump(
            exclude={"name"}, by_alias=False, exclude_none=True
        )
        payload.update(submission.translator_overrides())
        translated = translate_pipeline_manifest(payload)
        return pipeline_definition_from_profile_entry(
            submission.name,
            translated,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipelines", status_code=201)
def create_pipeline(
    submission: PipelineDefinitionSubmission,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_MANAGE)),
) -> JSONResponse:
    orchestrator = get_pipeline_orchestrator()
    definition = _definition_from_submission(submission)
    try:
        orchestrator.register(definition)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(status_code=201, content=definition.serialise())


@router.put("/pipelines/{pipeline}")
def update_pipeline(
    pipeline: str,
    submission: PipelineDefinitionSubmission,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_MANAGE)),
) -> JSONResponse:
    if submission.name != pipeline:
        raise HTTPException(status_code=400, detail="Pipeline name mismatch")

    orchestrator = get_pipeline_orchestrator()
    definition = _definition_from_submission(submission)
    orchestrator.upsert(definition)
    return JSONResponse(content=definition.serialise())


@router.delete("/pipelines/{pipeline}", status_code=204)
def delete_pipeline(
    pipeline: str,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_MANAGE)),
) -> Response:
    orchestrator = get_pipeline_orchestrator()
    try:
        orchestrator.deregister(pipeline)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown pipeline") from exc
    return Response(status_code=204)


@router.get("/pipelines")
def list_pipelines(
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> JSONResponse:
    orchestrator = get_pipeline_orchestrator()
    payload = [definition.serialise() for definition in orchestrator.list_pipelines()]
    return JSONResponse(content=payload)


@router.get("/pipelines/{pipeline}")
def describe_pipeline(
    pipeline: str,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> JSONResponse:
    orchestrator = get_pipeline_orchestrator()
    try:
        definition = orchestrator.get_pipeline(pipeline)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown pipeline") from exc
    return JSONResponse(content=definition.serialise())


@router.post("/pipelines/{pipeline}/runs", status_code=201)
def trigger_pipeline_run(
    pipeline: str,
    submission: PipelineRunSubmission,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_RUN)),
) -> JSONResponse:
    orchestrator = get_pipeline_orchestrator()
    try:
        run = orchestrator.trigger_run(
            pipeline,
            parameters=submission.parameters,
            submitted_by=_principal.identifier,
            roles=_principal.roles,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown pipeline") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=201, content=run.serialise())


@router.post("/runs/prune")
def prune_runs(
    submission: PipelinePruneRequest | None = None,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_MANAGE)),
) -> JSONResponse:
    orchestrator = get_pipeline_orchestrator()

    overrides = submission or PipelinePruneRequest()
    max_age = (
        timedelta(hours=overrides.max_age_hours)
        if overrides.max_age_hours is not None
        else None
    )
    result = orchestrator.prune_history(max_age=max_age, max_runs=overrides.max_runs)
    return JSONResponse(content=result.serialise())


@router.get("/runs/stats")
def run_statistics(
    include_durations: Annotated[
        bool,
        Query(
            description="Include duration summaries for each pipeline/status grouping.",
        ),
    ] = False,
    pipeline: Annotated[
        str | None,
        Query(description="Filter statistics to a specific pipeline"),
    ] = None,
    since: Annotated[
        str | None,
        Query(
            description="Restrict statistics to runs created on or after this ISO timestamp."
        ),
    ] = None,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> JSONResponse:
    """Return aggregated run statistics for the orchestrator.

    The payload groups counts by pipeline name and run status. Each entry has the
    shape ``{"count": <int>}``. When ``include_durations`` is true, a
    ``durations`` mapping with ``average_seconds``, ``min_seconds`` and
    ``max_seconds`` is also included for statuses with recorded runs::

        {
            "pipelines": {
                "render_shots": {
                    "succeeded": {
                        "count": 5,
                        "durations": {
                            "average_seconds": 42.0,
                            "min_seconds": 30.5,
                            "max_seconds": 55.2,
                        },
                    },
                    "failed": {"count": 1},
                }
            }
        }
    """

    orchestrator = get_pipeline_orchestrator()

    parsed_since: datetime | None = None
    if since is not None:
        try:
            parsed_since = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Invalid 'since' timestamp"
            ) from exc
        if parsed_since.tzinfo is None:
            parsed_since = parsed_since.replace(tzinfo=timezone.utc)
        else:
            parsed_since = parsed_since.astimezone(timezone.utc)

    pipeline_filter: str | None = None
    if pipeline is not None:
        trimmed = pipeline.strip()
        if not trimmed:
            raise HTTPException(
                status_code=400, detail="Invalid 'pipeline' parameter"
            )
        pipeline_filter = trimmed

    stats = orchestrator.aggregate_runs(
        include_durations=include_durations,
        since=parsed_since,
        pipeline=pipeline_filter,
    )
    return JSONResponse(content={"pipelines": stats})


@router.get("/workers/metrics")
def worker_metrics(
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> JSONResponse:
    """Return the current worker pool utilisation for the orchestrator."""

    orchestrator = get_pipeline_orchestrator()
    metrics = orchestrator.worker_pool_metrics()
    payload = {
        "max_workers": metrics.max_workers,
        "active_workers": metrics.active_workers,
    }
    return JSONResponse(content=payload)


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> JSONResponse:
    orchestrator = get_pipeline_orchestrator()
    try:
        payload = orchestrator.serialise_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return JSONResponse(content=payload)


@router.get("/runs")
def list_runs(
    pipeline: Annotated[
        str | None, Query(description="Filter runs for a pipeline")
    ] = None,
    status: Annotated[str | None, Query(description="Filter runs by status")] = None,
    submitted_by: Annotated[
        str | None, Query(description="Filter runs by submitting principal")
    ] = None,
    role: Annotated[
        str | None,
        Query(description="Filter runs submitted with the specified role"),
    ] = None,
    limit: Annotated[
        int | None, Query(gt=0, description="Maximum number of runs to return")
    ] = None,
    since: Annotated[
        str | None,
        Query(description="Return runs created on or after the provided ISO timestamp"),
    ] = None,
    before_id: Annotated[
        str | None,
        Query(
            alias="before_id",
            description="Return runs created before the provided run id",
        ),
    ] = None,
    before_created_at: Annotated[
        str | None,
        Query(
            alias="before_created_at",
            description="Return runs created before the provided ISO timestamp",
        ),
    ] = None,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> JSONResponse:
    orchestrator = get_pipeline_orchestrator()

    parsed_since: datetime | None = None
    if since is not None:
        try:
            parsed_since = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Invalid 'since' timestamp"
            ) from exc
        if parsed_since.tzinfo is None:
            parsed_since = parsed_since.replace(tzinfo=timezone.utc)
        else:
            parsed_since = parsed_since.astimezone(timezone.utc)

    if (before_id is None) ^ (before_created_at is None):
        raise HTTPException(
            status_code=400,
            detail="'before_id' and 'before_created_at' must be supplied together",
        )
    if before_id is not None and limit is None:
        raise HTTPException(
            status_code=400,
            detail="'limit' must be provided when using a pagination cursor",
        )
    if role is not None and not role.strip():
        raise HTTPException(status_code=400, detail="'role' must be non-empty")
    if submitted_by is not None and not submitted_by.strip():
        raise HTTPException(status_code=400, detail="'submitted_by' must be non-empty")

    parsed_before_created: datetime | None = None
    if before_created_at is not None:
        try:
            parsed_before_created = datetime.fromisoformat(before_created_at)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid 'before_created_at' timestamp",
            ) from exc
        if parsed_before_created.tzinfo is None:
            parsed_before_created = parsed_before_created.replace(tzinfo=timezone.utc)
        else:
            parsed_before_created = parsed_before_created.astimezone(timezone.utc)

    page = orchestrator.list_runs(
        pipeline=pipeline,
        status=status,
        submitted_by=submitted_by,
        role=role,
        limit=limit,
        since=parsed_since,
        before_id=before_id,
        before_created_at=parsed_before_created,
    )
    return JSONResponse(content=page.serialise())


def _encode_event(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    return b"data: " + data + b"\n\n"


_TERMINAL_STATUSES = {"succeeded", "failed"}
_HEARTBEAT_INTERVAL = 15.0
_HEARTBEAT_COMMENT = b": keep-alive\n\n"


async def _cancel_task(task: asyncio.Task[Any] | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    with suppress(asyncio.CancelledError, StopAsyncIteration):
        await task


async def _live_event_stream(
    events: AsyncIterator[Any],
) -> AsyncIterator[bytes]:
    heartbeat_task: asyncio.Task[None] | None = None
    event_task: asyncio.Task[Any] | None = None

    try:
        while True:
            if event_task is None:
                event_task = asyncio.create_task(anext(events))  # type: ignore[arg-type]
            if heartbeat_task is None:
                heartbeat_task = asyncio.create_task(asyncio.sleep(_HEARTBEAT_INTERVAL))

            done, _ = await asyncio.wait(
                {event_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if event_task in done:
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    return
                finally:
                    event_task = None

                payload = event.serialise()
                await _cancel_task(heartbeat_task)
                heartbeat_task = None

                if _should_stream_event(payload):
                    yield _encode_event(payload)
                    if payload.get("status") in _TERMINAL_STATUSES:
                        return
                await asyncio.sleep(0)

            if heartbeat_task in done:
                await _cancel_task(heartbeat_task)
                heartbeat_task = None
                yield _HEARTBEAT_COMMENT
    finally:
        await _cancel_task(event_task)
        await _cancel_task(heartbeat_task)


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> StreamingResponse:
    orchestrator = get_pipeline_orchestrator()
    try:
        live_events = orchestrator.watch_run_events(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc

    return StreamingResponse(
        _live_event_stream(live_events),
        media_type="text/event-stream",
    )


def _should_stream_event(event: dict[str, Any]) -> bool:
    """Return whether the event should be sent to streaming clients.

    The orchestrator records both run-level updates (``queued``, ``running``,
    ``succeeded`` and ``failed``) as well as verbose step lifecycle entries
    (``step_started``, ``step_succeeded`` and ``step_failed``).  The API is
    expected to expose the coarse-grained run status transitions to clients so
    they can quickly determine the outcome without processing the full event
    stream.  Filtering here keeps the underlying data untouched while presenting
    the simplified view required by the tests.
    """

    allowed_statuses = {"queued", "running", "succeeded", "failed"}
    return event.get("status") in allowed_statuses


app.include_router(router)

__all__ = ["app", "router"]
