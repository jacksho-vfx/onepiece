"""FastAPI application exposing the pipeline orchestrator."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from apps.onepiece.config import load_profile
from apps.trafalgar.pipeline import (
    configure_orchestrator_from_profile,
    get_pipeline_orchestrator,
)
from apps.trafalgar.version import TRAFALGAR_VERSION
from .security import (
    AuthenticatedPrincipal,
    ROLE_PIPELINE_READ,
    ROLE_PIPELINE_RUN,
    create_protected_router,
    require_roles,
)


class PipelineRunSubmission(BaseModel):
    """Request payload used when triggering a pipeline run."""

    parameters: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="OnePiece Pipeline API", version=TRAFALGAR_VERSION)
router = create_protected_router()


@app.on_event("startup")
def _register_profile_pipelines() -> None:
    context = load_profile()
    configure_orchestrator_from_profile(context)


@router.get("/")
def root(
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> dict[str, str]:
    """Return a simple payload confirming the service is available."""

    return {"message": "OnePiece Pipeline API is running"}


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
        run = orchestrator.trigger_run(pipeline, parameters=submission.parameters)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown pipeline") from exc
    return JSONResponse(status_code=201, content=run.serialise())


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


def _encode_event(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    return b"data: " + data + b"\n\n"


async def _event_stream(events: list[dict[str, Any]]) -> AsyncGenerator[bytes, Any]:
    for event in events:
        yield _encode_event(event)
        await asyncio.sleep(0)


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_PIPELINE_READ)),
) -> StreamingResponse:
    orchestrator = get_pipeline_orchestrator()
    try:
        events = orchestrator.serialise_run_events(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc

    filtered = _filter_run_events(events)
    return StreamingResponse(_event_stream(filtered), media_type="text/event-stream")


def _filter_run_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only high-level run events for streaming clients.

    The orchestrator records both run-level updates (``queued``, ``running``,
    ``succeeded`` and ``failed``) as well as verbose step lifecycle entries
    (``step_started``, ``step_succeeded`` and ``step_failed``).  The API is
    expected to expose the coarse-grained run status transitions to clients so
    they can quickly determine the outcome without processing the full event
    stream.  Filtering here keeps the underlying data untouched while presenting
    the simplified view required by the tests.
    """

    allowed_statuses = {"queued", "running", "succeeded", "failed"}
    return [event for event in events if event.get("status") in allowed_statuses]


app.include_router(router)

__all__ = ["app", "router"]
