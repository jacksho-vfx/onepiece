"""Client implementations for the pipeline CLI."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from queue import Queue
from typing import Any, Iterable, Iterator, Mapping, Protocol

import httpx

from apps.trafalgar.pipeline import (
    PipelineDefinition,
    get_pipeline_orchestrator,
    pipeline_definition_from_profile_entry,
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
    ) -> list[Mapping[str, Any]]: ...  # pragma: no cover - Protocol

    def get_definition(
        self, name: str
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

    def trigger_run(
        self, name: str, parameters: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

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
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

    def get_run(
        self, run_id: str
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

    def get_run_events(
        self, run_id: str
    ) -> list[Mapping[str, Any]]: ...  # pragma: no cover - Protocol

    def stream_events(
        self, run_id: str
    ) -> Iterable[Mapping[str, Any]]: ...  # pragma: no cover - Protocol

    def get_stats(
        self,
        *,
        since: str | None = None,
        include_durations: bool = False,
        pipeline: str | None = None,
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

    def worker_pool_metrics(
        self,
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

    def create_definition(
        self, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

    def update_definition(
        self, name: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

    def delete_definition(self, name: str) -> None: ...  # pragma: no cover - Protocol

    def prune_runs(
        self,
        *,
        max_age_hours: float | None = None,
        max_runs: int | None = None,
    ) -> Mapping[str, Any]: ...  # pragma: no cover - Protocol

    def close(self) -> None: ...  # pragma: no cover - Protocol


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

    def get_run_events(self, run_id: str) -> list[Mapping[str, Any]]:
        try:
            return [
                dict(event) for event in self._orchestrator.serialise_run_events(run_id)
            ]
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
        pipeline: str | None = None,
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

        pipeline_filter: str | None = None
        if pipeline is not None:
            pipeline_filter = pipeline.strip()
            if not pipeline_filter:
                raise PipelineClientError("Pipeline name must not be blank.")

        stats = self._orchestrator.aggregate_runs(
            since=parsed_since,
            include_durations=include_durations,
            pipeline=pipeline_filter,
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

    def get_run_events(self, run_id: str) -> list[Mapping[str, Any]]:
        response = self._request("GET", f"runs/{run_id}/events/history")
        payload = response.json()
        if not isinstance(payload, list):
            raise PipelineClientError("Pipeline API returned an unexpected payload.")
        events: list[Mapping[str, Any]] = []
        for event in payload:
            if isinstance(event, Mapping):
                events.append(event)
        return events

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
        pipeline: str | None = None,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if include_durations:
            params["include_durations"] = True
        if pipeline is not None:
            params["pipeline"] = pipeline
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


def _definition_from_submission_payload(
    payload: Mapping[str, Any],
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


def create_pipeline_client() -> PipelineClient:
    if _should_use_remote_transport():
        return RemotePipelineClient()
    return LocalPipelineClient()


__all__ = [
    "PipelineClient",
    "PipelineClientError",
    "LocalPipelineClient",
    "RemotePipelineClient",
    "create_pipeline_client",
]
