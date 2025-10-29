"""Typer application for interacting with the pipeline orchestrator."""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

import httpx
import typer

from apps.trafalgar.pipeline import get_pipeline_orchestrator
from apps.trafalgar.transport import (
    LEGACY_PIPELINE_API_URL_ENV,
    PIPELINE_API_URL_ENV,
    resolve_pipeline_api_timeout,
    resolve_pipeline_api_url,
    resolve_pipeline_auth_headers,
)


class PipelineClient(Protocol):
    """Protocol describing the pipeline operations used by the CLI."""

    def list_definitions(
        self,
    ) -> list[Mapping[str, Any]]:  # pragma: no cover - Protocol
        ...

    def get_definition(
        self, name: str
    ) -> Mapping[str, Any]:  # pragma: no cover - Protocol
        ...

    def trigger_run(
        self, name: str, parameters: Mapping[str, Any]
    ) -> Mapping[str, Any]:  # pragma: no cover - Protocol
        ...

    def close(self) -> None:  # pragma: no cover - Protocol
        ...


@dataclass(slots=True)
class PipelineClientError(RuntimeError):
    """Raised when orchestrator interactions fail."""

    message: str
    status_code: int | None = None

    def __str__(self) -> str:  # pragma: no cover - dataclass hook
        return self.message


class LocalPipelineClient:
    """Client that proxies calls to the in-process orchestrator."""

    def __init__(self) -> None:
        self._orchestrator = get_pipeline_orchestrator()

    def close(self) -> None:  # pragma: no cover - no cleanup required
        return None

    def list_definitions(self) -> list[Mapping[str, Any]]:
        definitions = self._orchestrator.list_pipelines()
        return [definition.serialise() for definition in definitions]

    def get_definition(self, name: str) -> Any:
        try:
            definition = self._orchestrator.get_pipeline(name)
        except KeyError as exc:
            raise PipelineClientError(str(exc), status_code=404) from exc
        return definition.serialise()

    def trigger_run(self, name: str, parameters: Mapping[str, Any]) -> Any:
        try:
            run = self._orchestrator.trigger_run(name, parameters=parameters)
        except KeyError as exc:
            raise PipelineClientError(str(exc), status_code=404) from exc
        return run.serialise()


class RemotePipelineClient:
    """Client that communicates with the Trafalgar pipeline API."""

    def __init__(self) -> None:
        base_url = _normalise_base_url(resolve_pipeline_api_url())
        timeout = resolve_pipeline_api_timeout()
        headers = resolve_pipeline_auth_headers()
        self._client = httpx.Client(base_url=base_url, timeout=timeout, headers=headers)

    def close(self) -> None:
        self._client.close()

    def list_definitions(self) -> list[Mapping[str, Any]]:
        response = self._request("GET", "pipelines")
        payload = response.json()
        if not isinstance(payload, list):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        definitions: list[Mapping[str, Any]] = []
        for item in payload:
            if isinstance(item, Mapping):
                definitions.append(dict(item))
        return definitions

    def get_definition(self, name: str) -> Mapping[str, Any]:
        definitions = self.list_definitions()
        for definition in definitions:
            if str(definition.get("name")) == name:
                return definition
        raise PipelineClientError(f"Pipeline '{name}' was not found.", status_code=404)

    def trigger_run(
        self, name: str, parameters: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        response = self._request(
            "POST",
            f"pipelines/{name}/runs",
            json={"parameters": dict(parameters)},
        )
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        return dict(payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise PipelineClientError("Unable to reach pipeline API.") from exc
        if response.is_success:
            return response
        detail = _extract_response_detail(response)
        raise PipelineClientError(detail, status_code=response.status_code)


def _normalise_base_url(url: str) -> str:
    stripped = url.strip().rstrip("/")
    if not stripped:
        stripped = "/pipeline"
    return stripped + "/"


def _extract_response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"Pipeline API request failed ({response.status_code})."
    if isinstance(payload, Mapping):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    text = response.text.strip()
    return text or f"Pipeline API request failed ({response.status_code})."


def _should_use_remote_transport() -> bool:
    force_remote = os.environ.get("ONEPIECE_PIPELINE_FORCE_REMOTE", "").lower()
    if force_remote in {"1", "true", "yes"}:
        return True

    force_local = os.environ.get("ONEPIECE_PIPELINE_FORCE_LOCAL", "").lower()
    if force_local in {"1", "true", "yes"}:
        return False

    for variable in (
        PIPELINE_API_URL_ENV,
        LEGACY_PIPELINE_API_URL_ENV,
        "ONEPIECE_PIPELINE_API_URL",
    ):
        value = os.environ.get(variable, "").strip()
        if value:
            return True
    return False


def _create_pipeline_client() -> PipelineClient:
    if _should_use_remote_transport():
        return RemotePipelineClient()
    return LocalPipelineClient()


def _format_pipeline_definition(definition: Mapping[str, Any]) -> Iterable[str]:
    name = str(definition.get("name", ""))
    display = definition.get("display_name")
    display_text = str(display) if display is not None else ""
    header = name
    if display_text and display_text != name:
        header = f"{name} ({display_text})"
    yield header

    description = definition.get("description")
    if isinstance(description, str) and description.strip():
        yield f"  {description.strip()}"

    parameters = definition.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        names = sorted(str(key) for key in parameters if str(key))
        if names:
            yield "  Parameters: " + ", ".join(names)


def _render_pipeline_details(definition: Mapping[str, Any]) -> None:
    name = str(definition.get("name", ""))
    typer.echo(f"Name: {name}")

    display = definition.get("display_name")
    display_text = str(display).strip() if display is not None else ""
    if display_text and display_text != name:
        typer.echo(f"Display name: {display_text}")

    description = definition.get("description")
    if isinstance(description, str) and description.strip():
        typer.echo(f"Description: {description.strip()}")

    parameters = definition.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        typer.echo("Parameters:")
        for key in sorted(parameters):
            value = parameters[key]
            typer.echo(f"  - {key}: {value}")
    else:
        typer.echo("Parameters: <none>")


def _parse_pipeline_parameters(raw: list[str] | None) -> dict[str, str]:
    parameters: dict[str, str] = {}
    if not raw:
        return parameters
    for item in raw:
        if "=" not in item:
            raise PipelineClientError(
                f"Invalid parameter '{item}'. Expected key=value pairs."
            )
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise PipelineClientError("Parameter keys cannot be empty.")
        parameters[key] = value.strip()
    return parameters


app = typer.Typer(
    name="pipeline",
    help="Interact with the OnePiece pipeline orchestrator.",
)


def _using_client() -> AbstractContextManager[PipelineClient]:
    class _Context(AbstractContextManager[PipelineClient]):
        def __init__(self) -> None:
            self._client = _create_pipeline_client()

        def __enter__(self) -> PipelineClient:
            return self._client

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            self._client.close()
            return None

    return _Context()


@app.command("list")
def list_pipelines() -> None:
    """List pipelines exposed by the orchestrator."""

    with _using_client() as client:
        try:
            definitions = client.list_definitions()
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if not definitions:
        typer.echo("No pipelines are currently registered with the orchestrator.")
        raise typer.Exit(code=0)

    for definition in definitions:
        for line in _format_pipeline_definition(definition):
            typer.echo(line)


@app.command("describe")
def describe_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier."),
) -> None:
    """Describe a specific pipeline."""

    with _using_client() as client:
        try:
            definition = client.get_definition(name)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    _render_pipeline_details(definition)


@app.command("run")
def run_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    *,
    parameters: list[str] | None = typer.Option(
        None,
        "--param",
        "-p",
        help="Key=value parameters forwarded to the orchestrator.",
    ),
) -> None:
    """Trigger a pipeline execution."""

    try:
        parsed_parameters = _parse_pipeline_parameters(parameters)
    except PipelineClientError as exc:
        raise typer.BadParameter(exc.message) from exc

    with _using_client() as client:
        try:
            run = client.trigger_run(name, parsed_parameters)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    pipeline_name = run.get("pipeline", name)
    run_id = run.get("id", "<unknown>")
    status = run.get("status", "unknown")
    typer.echo(f"Triggered pipeline '{pipeline_name}' (run id: {run_id}).")
    typer.echo(f"Current status: {status}")


__all__ = ["app"]
