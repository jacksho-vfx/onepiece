"""Typer application for interacting with the pipeline orchestrator."""

from __future__ import annotations

import os
import asyncio
import json
import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Queue
from typing import Any, Iterable, Iterator, Mapping, Protocol

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

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: str | None = None,
    ) -> list[Mapping[str, Any]]:  # pragma: no cover - Protocol
        ...

    def get_run(self, run_id: str) -> Mapping[str, Any]:  # pragma: no cover - Protocol
        ...

    def stream_events(
        self, run_id: str
    ) -> Iterable[Mapping[str, Any]]:  # pragma: no cover - Protocol
        ...

    def get_stats(
        self,
        *,
        since: str | None = None,
        include_durations: bool = False,
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

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: str | None = None,
    ) -> list[Mapping[str, Any]]:
        parsed_since: datetime | None = None
        if since is not None:
            try:
                parsed_since = datetime.fromisoformat(since)
            except ValueError as exc:
                raise PipelineClientError("Invalid 'since' timestamp.") from exc
            if parsed_since.tzinfo is None:
                parsed_since = parsed_since.replace(tzinfo=timezone.utc)
            else:
                parsed_since = parsed_since.astimezone(timezone.utc)
        runs = self._orchestrator.list_runs(
            pipeline=pipeline, status=status, limit=limit, since=parsed_since
        )
        return [run.serialise() for run in runs]

    def get_run(self, run_id: str) -> Any:
        try:
            return self._orchestrator.serialise_run(run_id)
        except KeyError as exc:
            raise PipelineClientError(str(exc), status_code=404) from exc

    def stream_events(self, run_id: str) -> Iterable[Mapping[str, Any]]:
        sentinel = object()
        queue: "Queue[object]" = Queue()

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)

                try:
                    events = self._orchestrator.watch_run_events(run_id)
                except KeyError as exc:
                    queue.put(PipelineClientError(str(exc), status_code=404))
                    queue.put(sentinel)
                    return

                async def _consume() -> None:
                    try:
                        async for event in events:
                            queue.put(event.serialise())
                            if event.status in {"succeeded", "failed"}:
                                break
                    finally:
                        queue.put(sentinel)

                loop.run_until_complete(_consume())
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as exc:  # pragma: no cover - defensive guard
                queue.put(exc)
                queue.put(sentinel)
            finally:
                asyncio.set_event_loop(None)
                loop.close()

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()

        while True:
            item = queue.get()
            if item is sentinel:
                thread.join()
                break
            if isinstance(item, Exception):
                thread.join()
                raise item
            yield item  # type: ignore[misc]

    def get_stats(
        self,
        *,
        since: str | None = None,
        include_durations: bool = False,
    ) -> Mapping[str, Any]:
        parsed_since: datetime | None = None
        if since is not None:
            try:
                parsed_since = datetime.fromisoformat(since)
            except ValueError as exc:
                raise PipelineClientError("Invalid 'since' timestamp.") from exc
            if parsed_since.tzinfo is None:
                parsed_since = parsed_since.replace(tzinfo=timezone.utc)
            else:
                parsed_since = parsed_since.astimezone(timezone.utc)

        stats = self._orchestrator.aggregate_runs(
            since=parsed_since, include_durations=include_durations
        )
        return {"pipelines": stats}


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

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: str | None = None,
    ) -> list[Mapping[str, Any]]:
        params: dict[str, Any] = {}
        if pipeline is not None:
            params["pipeline"] = pipeline
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = limit
        if since is not None:
            params["since"] = since
        response = self._request("GET", "runs", params=params or None)
        payload = response.json()
        if not isinstance(payload, list):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        runs: list[Mapping[str, Any]] = []
        for item in payload:
            if isinstance(item, Mapping):
                runs.append(dict(item))
        return runs

    def get_run(self, run_id: str) -> Mapping[str, Any]:
        response = self._request("GET", f"runs/{run_id}")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        return dict(payload)

    def stream_events(self, run_id: str) -> Iterable[Mapping[str, Any]]:
        def _generator() -> Iterator[Mapping[str, Any]]:
            try:
                with self._client.stream("GET", f"runs/{run_id}/events") as response:
                    if not response.is_success:
                        detail = _extract_response_detail(response)
                        raise PipelineClientError(
                            detail, status_code=response.status_code
                        )
                    for line in response.iter_lines():
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(payload, Mapping):
                            yield dict(payload)
            except httpx.RequestError as exc:
                raise PipelineClientError("Unable to reach pipeline API.") from exc

        return _generator()

    def get_stats(
        self,
        *,
        since: str | None = None,
        include_durations: bool = False,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if include_durations:
            params["include_durations"] = True
        response = self._request("GET", "runs/stats", params=params or None)
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


_MISSING = object()


def _normalise_parameter_definition(
    value: Any,
) -> tuple[bool, Any, str | None]:
    required = False
    default: Any = _MISSING
    description: str | None = None
    if isinstance(value, Mapping):
        if "required" in value:
            required = bool(value.get("required"))
        if "default" in value:
            default = value.get("default")
        raw_description = value.get("description")
        if isinstance(raw_description, str):
            stripped = raw_description.strip()
            if stripped:
                description = stripped
    else:
        default = value
    return required, default, description


def _format_parameter_default(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


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
        summaries: list[str] = []
        for key in sorted(parameters):
            required, default, _ = _normalise_parameter_definition(parameters[key])
            details: list[str] = []
            if required:
                details.append("required")
            if default is not _MISSING:
                details.append(f"default={_format_parameter_default(default)}")
            label = key
            if details:
                label = f"{key} (" + ", ".join(details) + ")"
            summaries.append(label)
        if summaries:
            yield "  Parameters: " + ", ".join(summaries)


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
            required, default, description = _normalise_parameter_definition(
                parameters[key]
            )
            details: list[str] = []
            if required:
                details.append("required")
            if default is not _MISSING:
                details.append(f"default={_format_parameter_default(default)}")
            suffix = f" ({', '.join(details)})" if details else ""
            typer.echo(f"  - {key}{suffix}")
            if description:
                typer.echo(f"      {description}")
    else:
        typer.echo("Parameters: <none>")


def _format_pipeline_run(run: Mapping[str, Any]) -> Iterable[str]:
    run_id = str(run.get("id", ""))
    pipeline = str(run.get("pipeline", ""))
    status = str(run.get("status", ""))
    created = str(run.get("created_at", ""))
    updated = str(run.get("updated_at", ""))

    yield f"Run {run_id}"
    yield f"  Pipeline: {pipeline}"
    yield f"  Status: {status}"
    yield f"  Created: {created}"
    yield f"  Updated: {updated}"

    parameters = run.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        yield "  Parameters:"
        for key in sorted(parameters):
            value = parameters[key]
            typer_line = f"    - {key}: {value}"
            yield typer_line
    else:
        yield "  Parameters: <none>"


def _format_run_event(event: Mapping[str, Any]) -> Iterable[str]:
    timestamp = str(event.get("timestamp", ""))
    status = str(event.get("status", ""))
    pipeline = str(event.get("pipeline", ""))
    yield f"[{timestamp}] {pipeline} - {status}"

    parameters = event.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        yield from _format_event_parameters(parameters)


def _format_event_parameters(parameters: Mapping[str, Any]) -> Iterable[str]:
    step_name = _coerce_display_text(parameters.get("step"))
    if step_name:
        yield f"  Step: {step_name}"

    event_metadata = parameters.get("event")
    if isinstance(event_metadata, Mapping) and event_metadata:
        event_name = _coerce_display_text(event_metadata.get("name"))
        if event_name:
            yield f"  Trigger event: {event_name}"
        payload = event_metadata.get("payload")
        if payload not in (None, {}):
            formatted = json.dumps(payload, sort_keys=True)
            yield f"  Trigger payload: {formatted}"

    error_text = _coerce_display_text(parameters.get("error"))
    if error_text:
        yield f"  Error: {error_text}"

    ignored_keys = {"step", "event", "error"}
    extras = [
        (str(key), parameters[key]) for key in parameters if key not in ignored_keys
    ]
    if extras:
        yield "  Parameters:"
        for key, value in sorted(extras, key=lambda item: item[0]):
            yield f"    - {key}: {value}"


def _coerce_display_text(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return ""


def _format_pipeline_statistics(stats: Mapping[str, Any]) -> Iterable[str]:
    pipelines = stats.get("pipelines")
    if not isinstance(pipelines, Mapping) or not pipelines:
        return []

    lines: list[str] = []
    for pipeline in sorted(pipelines):
        lines.append(f"Pipeline: {pipeline}")
        statuses = pipelines[pipeline]
        if not isinstance(statuses, Mapping) or not statuses:
            lines.append("  No runs recorded.")
            continue
        for status in sorted(statuses):
            entry = statuses[status]
            count = entry.get("count", 0)
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                count_int = 0
            plural = "s" if count_int != 1 else ""
            line = f"  {status}: {count_int} run{plural}"
            durations = entry.get("durations")
            if isinstance(durations, Mapping):
                average = durations.get("average_seconds")
                minimum = durations.get("min_seconds")
                maximum = durations.get("max_seconds")
                if all(
                    isinstance(value, (int, float))
                    for value in (average, minimum, maximum)
                ):
                    line += (
                        f" (avg {float(average):.2f}s, min {float(minimum):.2f}s, "  # type: ignore[arg-type]
                        f"max {float(maximum):.2f}s)"  # type: ignore[arg-type]
                    )
            lines.append(line)
    return lines


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


@app.command("runs")
def list_runs(
    pipeline: str | None = typer.Option(
        None,
        "--pipeline",
        "-p",
        help="Filter runs for a specific pipeline.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter runs by status.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Maximum number of runs to display.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Return runs created on or after the ISO timestamp.",
    ),
) -> None:
    """List pipeline runs recorded by the orchestrator."""

    with _using_client() as client:
        try:
            runs = client.list_runs(
                pipeline=pipeline, status=status, limit=limit, since=since
            )
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if not runs:
        typer.echo("No pipeline runs were found.")
        raise typer.Exit(code=0)

    for run in runs:
        for line in _format_pipeline_run(run):
            typer.echo(line)


@app.command("stats")
def show_statistics(
    include_durations: bool = typer.Option(
        False,
        "--include-durations",
        "-d",
        help="Display duration summaries for each status grouping.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Restrict statistics to runs created on or after the ISO timestamp.",
    ),
) -> None:
    """Display aggregated pipeline run statistics."""

    with _using_client() as client:
        try:
            stats = client.get_stats(since=since, include_durations=include_durations)
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    pipelines = stats.get("pipelines")
    if not isinstance(pipelines, Mapping) or not pipelines:
        typer.echo("No pipeline run statistics available.")
        raise typer.Exit(code=0)

    for line in _format_pipeline_statistics(stats):
        typer.echo(line)


@app.command("run-status")
def run_status(
    run_id: str = typer.Argument(..., help="Run identifier."),
) -> None:
    """Display metadata for a specific pipeline run."""

    with _using_client() as client:
        try:
            run = client.get_run(run_id)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    for line in _format_pipeline_run(run):
        typer.echo(line)


@app.command("watch")
def watch_run(
    run_id: str = typer.Argument(..., help="Run identifier."),
) -> None:
    """Stream live status events for a pipeline run."""

    with _using_client() as client:
        try:
            events = client.stream_events(run_id)
            for event in events:
                for line in _format_run_event(event):
                    typer.echo(line)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc


__all__ = ["app"]
