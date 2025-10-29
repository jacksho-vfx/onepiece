"""FastAPI application exposing a browser GUI for OnePiece commands."""

from __future__ import annotations

import asyncio
import os
import shlex
from typing import Any, Sequence

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typer.testing import CliRunner

from apps.onepiece.app import app as cli_app
from apps.trafalgar.web.dashboard import app as dashboard_app
from apps.trafalgar.web.render import app as render_app

from . import web_cli
from . import web_pipeline
from . import web_templates

CLI_PAGES = web_cli.CLI_PAGES
COMMAND_LOOKUP = web_cli.COMMAND_LOOKUP
ParameterSpec = web_cli.ParameterSpec
CommandSpec = web_cli.CommandSpec
PageSpec = web_cli.PageSpec

_extract_parameters = web_cli._extract_parameters

PipelineApiClient = web_pipeline.PipelineApiClient
PipelineApiError = web_pipeline.PipelineApiError
get_pipeline_client = web_pipeline.get_pipeline_client

_render_parameters = web_templates._render_parameters
_render_command = web_templates._render_command
_render_page = web_templates._render_page
_render_pipeline_page = web_templates._render_pipeline_page
_render_dashboard_page = web_templates._render_dashboard_page
_render_index = web_templates._render_index
_normalise_root_path = web_templates._normalise_root_path
_with_root_path = web_templates._with_root_path
_slugify = web_templates._slugify

app = FastAPI(title="Uta Control Center", docs_url=None, redoc_url=None)
app.mount("/dashboard", dashboard_app)
app.mount("/render", render_app)


class RunCommandRequest(BaseModel):
    path: list[str] = Field(..., description="CLI command segments to execute")
    extra_args: str = Field(
        "",
        description=(
            "Raw CLI arguments appended to the command (deprecated in favour of the "
            "structured 'arguments' payload)"
        ),
    )
    arguments: list[str] | None = Field(
        None, description="Structured CLI arguments appended to the command"
    )


class RunCommandResponse(BaseModel):
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    success: bool


class PipelineDefinitionPayload(BaseModel):
    name: str
    display_name: str | None = Field(None, alias="display_name")
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class PipelineRunPayload(BaseModel):
    id: str = Field(..., alias="id")
    pipeline: str
    status: str
    created_at: str | None = Field(None, alias="created_at")
    updated_at: str | None = Field(None, alias="updated_at")
    parameters: dict[str, Any] = Field(default_factory=dict)


class PipelineEventPayload(BaseModel):
    id: str
    pipeline: str
    status: str
    timestamp: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class TriggerPipelineRunRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    scope_root = request.scope.get("root_path", "")
    if not isinstance(scope_root, str):
        scope_root = ""
    root_path = _normalise_root_path(scope_root)
    query_tab = request.query_params.get("tab")
    active_slug = query_tab.lower() if isinstance(query_tab, str) else None
    if active_slug == "":
        active_slug = None
    return HTMLResponse(content=_render_index(root_path, active_slug=active_slug))


def _invoke_cli(arguments: Sequence[str]) -> RunCommandResponse:
    runner = CliRunner()
    result = runner.invoke(cli_app, list(arguments))
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return RunCommandResponse(
        command=list(arguments),
        exit_code=result.exit_code,
        stdout=stdout,
        stderr=stderr,
        success=result.exit_code == 0,
    )


def _split_extra_args(extra_args: str, *, posix: bool | None = None) -> list[str]:
    if not extra_args:
        return []
    if posix is None:
        posix = os.name != "nt"
    return shlex.split(extra_args, posix=posix)


@app.post("/api/run", response_model=RunCommandResponse)
async def run_command(payload: RunCommandRequest) -> RunCommandResponse:
    command_path = tuple(payload.path)
    if command_path not in COMMAND_LOOKUP:
        raise HTTPException(status_code=404, detail="Unknown command path")
    if payload.arguments is not None:
        extra_args = list(payload.arguments)
    else:
        try:
            extra_args = _split_extra_args(payload.extra_args)
        except ValueError as exc:  # pragma: no cover - user facing error
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    arguments = [*command_path, *extra_args]
    result = await asyncio.to_thread(_invoke_cli, arguments)
    return result


@app.get("/api/pipelines", response_model=list[PipelineDefinitionPayload])
async def list_pipelines(
    client: PipelineApiClient = Depends(get_pipeline_client),
) -> Any:
    try:
        return await client.list_pipelines()
    except PipelineApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post(
    "/api/pipelines/{pipeline}/runs",
    response_model=PipelineRunPayload,
    status_code=201,
)
async def trigger_pipeline_run(
    pipeline: str,
    submission: TriggerPipelineRunRequest,
    client: PipelineApiClient = Depends(get_pipeline_client),
) -> Any:
    try:
        return await client.trigger_run(pipeline, parameters=submission.parameters)
    except PipelineApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/api/pipelines/runs/{run_id}", response_model=PipelineRunPayload)
async def get_pipeline_run(
    run_id: str,
    client: PipelineApiClient = Depends(get_pipeline_client),
) -> Any:
    try:
        return await client.get_run(run_id)
    except PipelineApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get(
    "/api/pipelines/runs/{run_id}/events",
    response_model=list[PipelineEventPayload],
)
async def get_pipeline_events(
    run_id: str,
    client: PipelineApiClient = Depends(get_pipeline_client),
) -> list[dict[str, Any]]:
    try:
        return await client.get_run_events(run_id)
    except PipelineApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


__all__ = [
    "app",
    "RunCommandRequest",
    "RunCommandResponse",
    "CLI_PAGES",
    "COMMAND_LOOKUP",
    "PipelineApiClient",
    "PipelineApiError",
    "get_pipeline_client",
    "_render_index",
    "_slugify",
    "_split_extra_args",
]
