"""Typer application for interacting with the pipeline orchestrator."""

from __future__ import annotations

import os
import asyncio
import json
import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from queue import Queue
from typing import Any, Iterable, Iterator, Mapping, Protocol, Sequence

import httpx
import typer
import yaml

from apps.trafalgar.app import _load_pipeline_manifest
from apps.trafalgar.pipeline import (
    get_pipeline_orchestrator,
    pipeline_definition_from_profile_entry,
    PipelineDefinition,
)
from apps.trafalgar.pipeline_manifest import translate_pipeline_manifest
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
        submitted_by: str | None = None,
        role: str | None = None,
        limit: int | None = None,
        since: str | None = None,
        before_id: str | None = None,
        before_created_at: str | None = None,
    ) -> Mapping[str, Any]:  # pragma: no cover - Protocol
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

    def worker_pool_metrics(self) -> Mapping[str, Any]:  # pragma: no cover - Protocol
        ...

    def create_definition(
        self, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:  # pragma: no cover - Protocol
        ...

    def update_definition(
        self, name: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:  # pragma: no cover - Protocol
        ...

    def delete_definition(self, name: str) -> None:  # pragma: no cover - Protocol
        ...

    def prune_runs(
        self,
        *,
        max_age_hours: float | None = None,
        max_runs: int | None = None,
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
        submitted_by: str | None = None,
        role: str | None = None,
        limit: int | None = None,
        since: str | None = None,
        before_id: str | None = None,
        before_created_at: str | None = None,
    ) -> Any:
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
        if (before_id is None) ^ (before_created_at is None):
            raise PipelineClientError(
                "Both 'before_id' and 'before_created_at' must be provided."
            )
        if before_id is not None and limit is None:
            raise PipelineClientError(
                "A limit must be provided when using pagination cursors."
            )

        parsed_before_created: datetime | None = None
        if before_created_at is not None:
            try:
                parsed_before_created = datetime.fromisoformat(before_created_at)
            except ValueError as exc:
                raise PipelineClientError(
                    "Invalid 'before_created_at' timestamp."
                ) from exc
            if parsed_before_created.tzinfo is None:
                parsed_before_created = parsed_before_created.replace(
                    tzinfo=timezone.utc
                )
            else:
                parsed_before_created = parsed_before_created.astimezone(timezone.utc)

        page = self._orchestrator.list_runs(
            pipeline=pipeline,
            status=status,
            submitted_by=submitted_by,
            role=role,
            limit=limit,
            since=parsed_since,
            before_id=before_id,
            before_created_at=parsed_before_created,
        )
        return page.serialise()

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

    def worker_pool_metrics(self) -> Mapping[str, Any]:
        metrics = self._orchestrator.worker_pool_metrics()
        return {
            "max_workers": metrics.max_workers,
            "active_workers": metrics.active_workers,
        }

    def create_definition(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        definition = _definition_from_submission_payload(payload)
        try:
            self._orchestrator.register(definition)
        except ValueError as exc:
            raise PipelineClientError(str(exc), status_code=409) from exc
        return dict(definition.serialise())

    def update_definition(
        self, name: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        definition = _definition_from_submission_payload(payload)
        if definition.name != name:
            raise PipelineClientError("Pipeline name mismatch.", status_code=400)
        self._orchestrator.upsert(definition)
        return dict(definition.serialise())

    def delete_definition(self, name: str) -> None:
        try:
            self._orchestrator.deregister(name)
        except KeyError as exc:
            raise PipelineClientError(str(exc), status_code=404) from exc

    def prune_runs(
        self,
        *,
        max_age_hours: float | None = None,
        max_runs: int | None = None,
    ) -> Mapping[str, Any]:
        max_age: timedelta | None = None
        if max_age_hours is not None:
            max_age = timedelta(hours=max_age_hours)
        result = self._orchestrator.prune_history(max_age=max_age, max_runs=max_runs)
        return dict(result.serialise())


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
                definitions.append(item)
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
        return payload

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        submitted_by: str | None = None,
        role: str | None = None,
        limit: int | None = None,
        since: str | None = None,
        before_id: str | None = None,
        before_created_at: str | None = None,
    ) -> Mapping[str, Any]:
        if (before_id is None) ^ (before_created_at is None):
            raise PipelineClientError(
                "Both 'before_id' and 'before_created_at' must be provided."
            )
        if before_id is not None and limit is None:
            raise PipelineClientError(
                "A limit must be provided when using pagination cursors."
            )
        params: dict[str, Any] = {}
        if pipeline is not None:
            params["pipeline"] = pipeline
        if status is not None:
            params["status"] = status
        if submitted_by is not None:
            params["submitted_by"] = submitted_by
        if role is not None:
            params["role"] = role
        if limit is not None:
            params["limit"] = limit
        if since is not None:
            params["since"] = since
        if before_id is not None:
            params["before_id"] = before_id
        if before_created_at is not None:
            params["before_created_at"] = before_created_at
        response = self._request("GET", "runs", params=params or None)
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        return payload

    def get_run(self, run_id: str) -> Mapping[str, Any]:
        response = self._request("GET", f"runs/{run_id}")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        return payload

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
        return payload

    def worker_pool_metrics(self) -> Mapping[str, Any]:
        response = self._request("GET", "workers/metrics")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        return payload

    def create_definition(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        response = self._request("POST", "pipelines", json=dict(payload))
        body = response.json()
        if not isinstance(body, Mapping):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        return body

    def update_definition(
        self, name: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        response = self._request("PUT", f"pipelines/{name}", json=dict(payload))
        body = response.json()
        if not isinstance(body, Mapping):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        return body

    def delete_definition(self, name: str) -> None:
        self._request("DELETE", f"pipelines/{name}")

    def prune_runs(
        self,
        *,
        max_age_hours: float | None = None,
        max_runs: int | None = None,
    ) -> Mapping[str, Any]:
        payload: dict[str, Any] = {}
        if max_age_hours is not None:
            payload["max_age_hours"] = max_age_hours
        if max_runs is not None:
            payload["max_runs"] = max_runs
        kwargs: dict[str, Any] = {}
        if payload:
            kwargs["json"] = payload
        response = self._request("POST", "runs/prune", **kwargs)
        body = response.json()
        if not isinstance(body, Mapping):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        return body

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


def _definition_from_submission_payload(
    payload: Mapping[str, Any]
) -> "PipelineDefinition":
    name_value = payload.get("name")
    if not isinstance(name_value, str) or not name_value.strip():
        raise PipelineClientError(
            "Pipeline submission must include a non-empty 'name'.",
            status_code=400,
        )
    name = name_value.strip()
    config = {key: value for key, value in payload.items() if key != "name"}
    try:
        translated = translate_pipeline_manifest(config)
        return pipeline_definition_from_profile_entry(name, translated)
    except (KeyError, TypeError, ValueError) as exc:
        raise PipelineClientError(str(exc), status_code=400) from exc


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

    initiator = _coerce_display_text(run.get("submitted_by"))
    if initiator:
        yield f"  Submitted by: {initiator}"
        role_list = _normalise_roles(run.get("roles"))
        if role_list:
            yield "  Roles: " + ", ".join(role_list)

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

    error_message = _coerce_display_text(parameters.get("error_message"))
    error_type = _coerce_display_text(parameters.get("error_type"))
    error_fallback = _coerce_display_text(parameters.get("error"))
    if error_message and error_type:
        yield f"  Error: {error_message} ({error_type})"
    elif error_message:
        yield f"  Error: {error_message}"
    elif error_type and error_fallback:
        yield f"  Error: {error_fallback} ({error_type})"
    elif error_fallback:
        yield f"  Error: {error_fallback}"
    elif error_type:
        yield f"  Error: {error_type}"

    traceback_value = parameters.get("traceback")
    traceback_lines: list[str] = []
    if isinstance(traceback_value, str):
        text = traceback_value.rstrip()
        if text:
            traceback_lines = text.splitlines()
    elif isinstance(traceback_value, Sequence) and not isinstance(
        traceback_value, (str, bytes, bytearray)
    ):
        traceback_lines = [str(line).rstrip("\n") for line in traceback_value]

    if traceback_lines:
        yield "  Traceback:"
        for line in traceback_lines:
            if line:
                yield f"    {line}"
            else:
                yield ""

    ignored_keys = {
        "step",
        "event",
        "error",
        "error_type",
        "error_message",
        "traceback",
    }
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


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalise_roles(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items: Iterable[str] = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        items = value
    else:
        return []
    seen: set[str] = set()
    roles: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        roles.append(text)
    return sorted(roles)


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


def _format_worker_metrics(metrics: Mapping[str, Any]) -> str:
    active = metrics.get("active_workers")
    try:
        active_workers = int(active)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        active_workers = 0

    limit_value = metrics.get("max_workers")
    if limit_value is None:
        limit_display = "unbounded"
    else:
        try:
            limit_display = str(int(limit_value))
        except (TypeError, ValueError):
            limit_display = str(limit_value)

    return f"Active workers: {active_workers} (limit: {limit_display})."


def _format_pipeline_prune_summary(result: Mapping[str, Any]) -> Iterable[str]:
    removed_runs = _coerce_int(result.get("removed_runs"))
    removed_events = _coerce_int(result.get("removed_events"))
    remaining_runs = _coerce_int(result.get("remaining_runs"))
    lines = [
        f"Removed {removed_runs} runs and {removed_events} events from the store.",
        f"{remaining_runs} runs remain after pruning.",
    ]

    removed_by_pipeline = result.get("removed_runs_by_pipeline")
    if isinstance(removed_by_pipeline, Mapping) and removed_by_pipeline:
        details = ", ".join(
            f"{pipeline}: {_coerce_int(count)}"
            for pipeline, count in sorted(removed_by_pipeline.items())
        )
        lines.append(f"Per-pipeline removals: {details}.")

    policy_parts: list[str] = []
    max_age_seconds = result.get("max_age_seconds")
    if isinstance(max_age_seconds, (int, float)):
        hours = float(max_age_seconds) / 3600
        policy_parts.append(f"max age {hours:.2f} hours")
    max_runs = result.get("max_runs")
    if isinstance(max_runs, (int, float)):
        policy_parts.append(f"max runs {int(max_runs)}")
    if policy_parts:
        lines.append("Retention applied: " + ", ".join(policy_parts) + ".")

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


def _load_pipeline_submission(
    manifest: Path, *, name: str | None = None
) -> dict[str, Any]:
    try:
        payload = _load_pipeline_manifest(manifest)
    except typer.BadParameter as exc:
        raise typer.BadParameter(str(exc), param_hint="manifest") from exc

    pipelines_section = payload.get("pipelines")
    if isinstance(pipelines_section, Mapping):
        if name is None:
            if len(pipelines_section) != 1:
                raise typer.BadParameter(
                    "Manifest contains multiple pipelines; provide --name to select one.",
                    param_hint="manifest",
                )
            selected_name, config_payload = next(iter(pipelines_section.items()))
        else:
            try:
                config_payload = pipelines_section[name]
            except KeyError as exc:
                raise typer.BadParameter(
                    f"Manifest does not include a pipeline named '{name}'.",
                    param_hint="--name",
                ) from exc
            selected_name = name
        if not isinstance(config_payload, Mapping):
            raise typer.BadParameter(
                "Pipeline entries must be mappings.", param_hint="manifest"
            )
    else:
        raw_name = name or payload.get("name")
        if not raw_name:
            raise typer.BadParameter(
                "Pipeline manifests must declare a 'name'.", param_hint="manifest"
            )
        selected_name = str(raw_name)
        if name is not None and selected_name != name:
            raise typer.BadParameter(
                "Pipeline manifest name does not match the '--name' option "
                f"('{selected_name}' != '{name}').",
                param_hint="--name",
            )
        config_payload = payload

    submission = dict(config_payload)
    submission["name"] = str(selected_name)
    return submission


def _serialised_definition_to_manifest(definition: Mapping[str, Any]) -> dict[str, Any]:
    manifest: dict[str, Any] = {}

    name = definition.get("name")
    if name is not None:
        manifest["name"] = str(name)

    version = definition.get("version")
    if version is not None:
        manifest["version"] = version

    for field in ("display_name", "description"):
        value = definition.get(field)
        if isinstance(value, str) and value.strip():
            manifest[field] = value

    metadata = definition.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        metadata_payload = dict(metadata)
        metadata_version = metadata_payload.get("version")
        if metadata_version is not None:
            if "version" not in manifest:
                manifest["version"] = metadata_version
            if manifest.get("version") == metadata_version:
                metadata_payload.pop("version", None)
        if metadata_payload:
            manifest["metadata"] = _normalise_manifest_value(metadata_payload)

    parameters = definition.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        manifest["parameters"] = {
            str(key): _normalise_manifest_value(value)
            for key, value in parameters.items()
            if isinstance(value, Mapping)
        }

    steps = definition.get("steps")
    sequential_steps: list[dict[str, Any]] = []
    event_triggers: list[dict[str, Any]] = []
    if isinstance(steps, Sequence):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            manifest_step = _serialised_step_to_manifest(step)
            trigger = step.get("trigger")
            depends_on = _normalise_dependencies(trigger)

            if depends_on:
                manifest_step["after"] = (
                    depends_on[0] if len(depends_on) == 1 else depends_on
                )

            if isinstance(trigger, Mapping):
                kind = str(trigger.get("kind", "sequential")).lower()
            else:
                kind = "sequential"

            if kind == "event":
                event_name = (
                    trigger.get("event") if isinstance(trigger, Mapping) else None
                )
                if not isinstance(event_name, str) or not event_name:
                    sequential_steps.append(manifest_step)
                    continue
                trigger_entry: dict[str, Any] = {"on": event_name}
                filters = (
                    trigger.get("filters") if isinstance(trigger, Mapping) else None
                )
                if isinstance(filters, Mapping) and filters:
                    trigger_entry["filters"] = _normalise_manifest_value(filters)
                trigger_entry["steps"] = [manifest_step]
                event_triggers.append(trigger_entry)
            else:
                sequential_steps.append(manifest_step)

    if sequential_steps:
        manifest["steps"] = sequential_steps
    if event_triggers:
        manifest["triggers"] = event_triggers

    return manifest


def _normalise_manifest_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise_manifest_value(val) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalise_manifest_value(item) for item in value]
    return value


def _serialised_step_to_manifest(step: Mapping[str, Any]) -> dict[str, Any]:
    manifest_step: dict[str, Any] = {}

    name = step.get("name")
    manifest_step["id"] = str(name) if name is not None else ""

    provider = step.get("provider")
    manifest_step["uses"] = str(provider) if provider is not None else ""

    config = step.get("config")
    if isinstance(config, Mapping) and config:
        manifest_step["with"] = _normalise_manifest_value(config)

    metadata = step.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        manifest_step["metadata"] = _normalise_manifest_value(metadata)

    return manifest_step


def _normalise_dependencies(trigger: Any) -> list[str]:
    if not isinstance(trigger, Mapping):
        return []
    dependencies = trigger.get("depends_on")
    if dependencies is None:
        return []
    if isinstance(dependencies, Sequence) and not isinstance(
        dependencies, (str, bytes, bytearray)
    ):
        return [str(dep) for dep in dependencies if str(dep)]
    return [str(dependencies)] if str(dependencies) else []


def _write_manifest(path: Path, manifest: Mapping[str, Any], *, format: str) -> None:
    format_normalised = format.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_normalised == "yaml":
        text = yaml.safe_dump(manifest, sort_keys=False)
    elif format_normalised == "toml":
        text = _render_manifest_toml(manifest)
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"Unsupported manifest format: {format}")
    path.write_text(text, encoding="utf-8")


def _resolve_manifest_format(output: Path, requested: str | None) -> str:
    if requested:
        candidate = requested.lower()
        if candidate not in {"toml", "yaml"}:
            raise typer.BadParameter(
                "Format must be either 'toml' or 'yaml'.",
                param_hint="--format",
            )
        return candidate

    suffix = output.suffix.lower()
    if suffix == ".toml":
        return "toml"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    return "toml"


def _render_manifest_toml(manifest: Mapping[str, Any]) -> str:
    lines: list[str] = []

    for key, value in manifest.items():
        if key in {"metadata", "parameters", "steps", "triggers"}:
            continue
        if value is None:
            continue
        lines.append(f"{key} = {_format_toml_scalar(value)}")

    metadata = manifest.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        if lines:
            lines.append("")
        lines.append("[metadata]")
        _render_table_body("metadata", metadata, lines)

    parameters = manifest.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        if lines:
            lines.append("")
        for name, definition in parameters.items():
            if not isinstance(definition, Mapping) or not definition:
                continue
            lines.append(f"[parameters.{name}]")
            _render_table_body(f"parameters.{name}", definition, lines)

    steps = manifest.get("steps")
    if isinstance(steps, Sequence) and steps:
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            if lines:
                lines.append("")
            lines.append("[[steps]]")
            _render_table_body("steps", step, lines)

    triggers = manifest.get("triggers")
    if isinstance(triggers, Sequence) and triggers:
        for trigger in triggers:
            if not isinstance(trigger, Mapping):
                continue
            if lines:
                lines.append("")
            lines.append("[[triggers]]")
            _render_table_body("triggers", trigger, lines)

    return "\n".join(lines) + "\n"


def _render_table_body(
    section: str, table: Mapping[str, Any], lines: list[str]
) -> None:
    scalars: list[tuple[str, Any]] = []
    nested_tables: list[tuple[str, Mapping[str, Any]]] = []
    array_tables: list[tuple[str, Sequence[Mapping[str, Any]]]] = []

    for key, value in table.items():
        if value is None:
            continue
        if isinstance(value, Mapping):
            nested_tables.append((key, value))
        elif _is_array_of_tables(value):
            array_tables.append((key, value))
        else:
            scalars.append((key, value))

    for key, value in scalars:
        lines.append(f"{key} = {_format_toml_scalar(value)}")

    for key, value in nested_tables:
        lines.append("")
        lines.append(f"[{section}.{key}]")
        _render_table_body(f"{section}.{key}", value, lines)

    for key, entries in array_tables:
        for entry in entries:
            lines.append("")
            lines.append(f"[[{section}.{key}]]")
            _render_table_body(f"{section}.{key}", entry, lines)


def _is_array_of_tables(value: Any) -> bool:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value) and all(isinstance(item, Mapping) for item in value)
    return False


def _format_toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ", ".join(_format_toml_scalar(item) for item in value) + "]"
    return json.dumps(value)


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


_VALID_OUTPUT_FORMATS = {"text", "json"}


def _resolve_output_format(raw: str) -> str:
    value = raw.strip().lower()
    if not value:
        return "text"
    if value not in _VALID_OUTPUT_FORMATS:
        raise typer.BadParameter(
            "--format must be either 'text' or 'json'.",
            param_hint="--format",
        )
    return value


@app.command("list")
def list_pipelines(
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """List pipelines exposed by the orchestrator."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            definitions = client.list_definitions()
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(definitions, indent=2))
        return

    if not definitions:
        typer.echo("No pipelines are currently registered with the orchestrator.")
        raise typer.Exit(code=0)

    for definition in definitions:
        for line in _format_pipeline_definition(definition):
            typer.echo(line)


@app.command("describe")
def describe_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Describe a specific pipeline."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            definition = client.get_definition(name)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(definition, indent=2))
        return

    _render_pipeline_details(definition)


@app.command("pull")
def pull_pipeline_definition(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Destination manifest file (TOML or YAML).",
    ),
    manifest_format: str | None = typer.Option(
        None,
        "--format",
        "-f",
        help="Output format ('toml' or 'yaml'). Defaults to the --output suffix.",
    ),
) -> None:
    """Fetch a pipeline definition and write it to a manifest file."""

    with _using_client() as client:
        try:
            definition = client.get_definition(name)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    manifest = _serialised_definition_to_manifest(definition)
    selected_format = _resolve_manifest_format(output, manifest_format)

    try:
        _write_manifest(output, manifest, format=selected_format)
    except OSError as exc:  # pragma: no cover - depends on filesystem errors
        typer.echo(f"Failed to write manifest: {exc}")
        raise typer.Exit(code=1) from exc

    pipeline_name = manifest.get("name") or name
    typer.echo(
        "Pipeline '{pipeline}' written to {fmt} manifest at {path}.".format(
            pipeline=pipeline_name,
            fmt=selected_format.upper(),
            path=output,
        )
    )


@app.command("push")
def push_pipeline_definition(
    manifest: Path = typer.Argument(..., help="TOML or YAML pipeline manifest."),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Pipeline name when the manifest contains multiple entries.",
    ),
) -> None:
    """Register a new pipeline definition from a manifest file."""

    submission = _load_pipeline_submission(manifest, name=name)

    with _using_client() as client:
        try:
            result = client.create_definition(submission)
        except PipelineClientError as exc:
            if exc.status_code == 400:
                raise typer.BadParameter(exc.message, param_hint="manifest") from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            if exc.status_code == 409:
                raise typer.Exit(code=1) from exc
            raise typer.Exit(code=1) from exc

    pipeline_name = str(result.get("name", submission["name"]))
    typer.echo(
        f"Pipeline '{pipeline_name}' created from {manifest.resolve()}.",
    )


@app.command("update")
def update_pipeline_definition(
    manifest: Path = typer.Argument(..., help="TOML or YAML pipeline manifest."),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Pipeline name when the manifest contains multiple entries.",
    ),
) -> None:
    """Replace an existing pipeline definition from a manifest file."""

    submission = _load_pipeline_submission(manifest, name=name)
    pipeline_name = str(submission["name"])

    with _using_client() as client:
        try:
            result = client.update_definition(pipeline_name, submission)
        except PipelineClientError as exc:
            if exc.status_code == 400:
                raise typer.BadParameter(exc.message, param_hint="manifest") from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    resolved_name = str(result.get("name", pipeline_name))
    typer.echo(
        f"Pipeline '{resolved_name}' updated from {manifest.resolve()}.",
    )


@app.command("delete")
def delete_pipeline_definition(
    name: str = typer.Argument(..., help="Pipeline identifier to remove."),
) -> None:
    """Delete a pipeline definition from the orchestrator."""

    with _using_client() as client:
        try:
            client.delete_definition(name)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message, param_hint="name") from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    typer.echo(f"Pipeline '{name}' deleted from the orchestrator.")


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
    initiator = _coerce_display_text(run.get("submitted_by"))
    if initiator:
        typer.echo(f"Initiated by: {initiator}")
        role_list = _normalise_roles(run.get("roles"))
        if role_list:
            typer.echo("Roles: " + ", ".join(role_list))


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
    submitted_by: str | None = typer.Option(
        None,
        "--submitted-by",
        help="Filter runs by the submitting principal.",
    ),
    role: str | None = typer.Option(
        None,
        "--role",
        help="Filter runs that include the specified submitting role.",
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
    before_id: str | None = typer.Option(
        None,
        "--before-id",
        help="Return runs created before the provided run id.",
    ),
    before_created_at: str | None = typer.Option(
        None,
        "--before-created-at",
        help="Return runs created before the provided ISO timestamp.",
    ),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """List pipeline runs recorded by the orchestrator."""

    output_format = _resolve_output_format(format)

    if (before_id is None) ^ (before_created_at is None):
        raise typer.BadParameter(
            "Both --before-id and --before-created-at must be provided together."
        )
    if before_id is not None and limit is None:
        raise typer.BadParameter(
            "--limit must be provided when using pagination cursors."
        )
    if role is not None and not role.strip():
        raise typer.BadParameter("--role must be a non-empty value.")
    if submitted_by is not None and not submitted_by.strip():
        raise typer.BadParameter("--submitted-by must be a non-empty value.")

    with _using_client() as client:
        try:
            page = client.list_runs(
                pipeline=pipeline,
                status=status,
                submitted_by=submitted_by,
                role=role,
                limit=limit,
                since=since,
                before_id=before_id,
                before_created_at=before_created_at,
            )
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(page, indent=2))
        return

    runs_payload = page.get("runs") if isinstance(page, Mapping) else None
    runs_list = runs_payload if isinstance(runs_payload, list) else []

    if not runs_list:
        typer.echo("No pipeline runs were found.")
        raise typer.Exit(code=0)

    for run in runs_list:
        for line in _format_pipeline_run(run):
            typer.echo(line)

    cursor_payload = page.get("next_cursor") if isinstance(page, Mapping) else None
    if isinstance(cursor_payload, Mapping):
        cursor_before_id = cursor_payload.get("before_id")
        cursor_before_created_at = cursor_payload.get("before_created_at")
        if cursor_before_id and cursor_before_created_at:
            typer.echo(
                "More runs available. Re-run with --before-id"
                f" {cursor_before_id} --before-created-at {cursor_before_created_at}."
            )


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
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Display aggregated pipeline run statistics."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            stats = client.get_stats(since=since, include_durations=include_durations)
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(stats, indent=2))
        return

    pipelines = stats.get("pipelines")
    if not isinstance(pipelines, Mapping) or not pipelines:
        typer.echo("No pipeline run statistics available.")
        raise typer.Exit(code=0)

    for line in _format_pipeline_statistics(stats):
        typer.echo(line)


@app.command("workers")
def show_worker_metrics(
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Display current worker pool utilisation."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            metrics = client.worker_pool_metrics()
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(metrics, indent=2))
        return

    typer.echo(_format_worker_metrics(metrics))


@app.command("prune")
def prune_history(
    max_age_hours: float | None = typer.Option(
        None,
        "--max-age-hours",
        help="Prune runs created before the provided number of hours ago.",
        min=0.0,
    ),
    max_runs: int | None = typer.Option(
        None,
        "--max-runs",
        help="Retain at most this many recent runs when pruning.",
        min=0,
    ),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Apply pipeline run retention policies and report the outcome."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            result = client.prune_runs(
                max_age_hours=max_age_hours,
                max_runs=max_runs,
            )
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(result, indent=2))
        return

    for line in _format_pipeline_prune_summary(result):
        typer.echo(line)


@app.command("run-status")
def run_status(
    run_id: str = typer.Argument(..., help="Run identifier."),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Display metadata for a specific pipeline run."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            run = client.get_run(run_id)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(run, indent=2))
        return

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
