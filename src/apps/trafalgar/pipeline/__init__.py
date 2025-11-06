"""Pipeline orchestration helpers shared across Trafalgar services."""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, AsyncIterator, Callable, Iterable, Iterator, Mapping, cast
import uuid

from apps.onepiece.config import ProfileContext
from apps.trafalgar.providers import pipeline_executor
from libraries.pipeline.factories import pipeline_from_config
from libraries.pipeline.models import Pipeline, PipelineStep

from .parameters import ParameterDefinition, _parse_parameter_definitions
from .storage import (
    PipelineDefinitionStore,
    PipelinePruneResult,
    PipelineRetentionPolicy,
    PipelineRun,
    PipelineRunEvent,
    PipelineRunPage,
    PipelineRunStore,
    _serialise_exception,
)

logger = logging.getLogger(__name__)
PROVIDER_REFERENCE_METADATA_KEY = pipeline_executor.PROVIDER_REFERENCE_METADATA_KEY


def _coerce_enabled_flag(pipeline_name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return True
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    msg = f"pipeline '{pipeline_name}' has invalid 'enabled' value"
    raise ValueError(msg)


@dataclass(slots=True)
class PipelineDefinition:
    """A lightweight description of a runnable pipeline."""

    name: str
    pipeline: Pipeline
    display_name: str | None = None
    description: str | None = None
    parameters: Mapping[str, ParameterDefinition] = field(default_factory=dict)
    version: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        if not self.name:
            msg = "pipeline definitions require a name"
            raise ValueError(msg)
        if not isinstance(self.pipeline, Pipeline):
            msg = "pipeline definitions require a Pipeline instance"
            raise TypeError(msg)
        if self.parameters is None:
            object.__setattr__(self, "parameters", {})
        else:
            parsed = _parse_parameter_definitions(
                cast(Mapping[str, Any], self.parameters),
                location=f"pipeline '{self.name}'",
            )
            object.__setattr__(self, "parameters", parsed)

        version = self.version
        if version is not None:
            text = str(version).strip()
            object.__setattr__(self, "version", text or None)
        if self.version is not None and "version" not in self.pipeline.metadata:
            metadata = dict(self.pipeline.metadata)
            metadata["version"] = self.version
            object.__setattr__(
                self, "pipeline", replace(self.pipeline, metadata=metadata)
            )

        enabled_flag = self.enabled
        if isinstance(enabled_flag, bool):
            enabled = enabled_flag
        else:
            enabled = _coerce_enabled_flag(self.name, enabled_flag)
        object.__setattr__(self, "enabled", enabled)

    def serialise(self) -> Mapping[str, Any]:
        steps = [self._serialise_step(step) for step in self.pipeline.steps]
        providers = {step["name"]: step["provider"] for step in steps}
        dependency_graph = {
            step["name"]: step["trigger"]["depends_on"] for step in steps
        }

        payload = {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "parameters": {
                name: definition.serialise()
                for name, definition in sorted(self.parameters.items())
            },
            "metadata": dict(self.pipeline.metadata),
            "steps": steps,
            "providers": providers,
            "dependency_graph": dependency_graph,
            "enabled": self.enabled,
        }
        if self.version is not None:
            payload["version"] = self.version
        return payload

    def _serialise_step(self, step: PipelineStep) -> Mapping[str, Any]:
        trigger = step.trigger
        metadata = dict(step.metadata)
        provider_reference = metadata.pop(PROVIDER_REFERENCE_METADATA_KEY, None)
        return {
            "name": step.name,
            "provider": (
                provider_reference
                if provider_reference is not None
                else self._serialise_provider(step.provider)
            ),
            "config": dict(step.config),
            "metadata": metadata,
            "trigger": {
                "kind": trigger.kind,
                "depends_on": list(trigger.depends_on),
                "event": trigger.event,
                "filters": dict(trigger.filters),
            },
        }

    @staticmethod
    def _serialise_provider(provider: Any) -> str:
        if isinstance(provider, str):
            return provider

        module = getattr(provider, "__module__", None)
        qualname = getattr(provider, "__qualname__", None)
        if module and qualname:
            return f"{module}:{qualname}"

        name = getattr(provider, "__name__", None)
        if module and name:
            return f"{module}:{name}"

        return repr(provider)

    def resolve_parameters(
        self, provided: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        supplied = dict(provided or {})
        schema = self.parameters
        if not schema:
            return supplied

        resolved: dict[str, Any] = {}

        unknown = [name for name in supplied if name not in schema]
        if unknown:
            details = ", ".join(sorted(unknown))
            msg = f"pipeline '{self.name}' does not define parameters: {details}"
            raise ValueError(msg)

        for name, definition in schema.items():
            value_source = "provided"
            if name in supplied:
                raw_value = supplied.pop(name)
            elif definition.has_default:
                raw_value = definition.default
                value_source = "default"
            elif definition.required:
                msg = f"pipeline '{self.name}' requires parameter '{name}'"
                raise ValueError(msg)
            else:
                continue
            try:
                resolved_value = definition.coerce(raw_value)
            except ValueError as exc:
                msg = (
                    f"pipeline '{self.name}' parameter '{name}' has invalid"
                    f" {value_source} value: {exc}"
                )
                raise ValueError(msg) from exc
            resolved[name] = resolved_value

        if supplied:
            details = ", ".join(sorted(supplied))
            msg = f"pipeline '{self.name}' does not define parameters: {details}"
            raise ValueError(msg)

        return resolved


@dataclass(frozen=True)
class WorkerPoolMetrics:
    """Snapshot of the orchestrator worker pool utilisation."""

    max_workers: int | None
    active_workers: int


class PipelineOrchestrator:
    """Pipeline orchestrator used by the Trafalgar tooling layer.

    Runs and events are persisted through a configurable :class:`PipelineRunStore`.
    """

    def __init__(
        self,
        definitions: Iterable[PipelineDefinition] | None = None,
        *,
        store: PipelineRunStore | None = None,
        definition_store: PipelineDefinitionStore | None = None,
        executor: pipeline_executor.PipelineExecutor | None = None,
        worker_pool: ThreadPoolExecutor | None = None,
        max_workers: int = 1,
        retention: PipelineRetentionPolicy | None = None,
    ) -> None:
        self._definitions: dict[str, PipelineDefinition] = {}
        self._lock = Lock()
        self._store = store or PipelineRunStore()
        self._definition_store = definition_store
        self._executor = executor or pipeline_executor.PipelineExecutor()
        if max_workers < 1:
            msg = "max_workers must be at least 1"
            raise ValueError(msg)
        if worker_pool is None:
            worker_pool = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="pipeline-runs"
            )
        self._worker_pool = worker_pool
        derived_max_workers = self._determine_max_workers(worker_pool)
        if derived_max_workers is None and worker_pool is None:
            derived_max_workers = max_workers
        self._max_workers = derived_max_workers
        self._shutdown = False
        self._pending: set[Future[None]] = set()
        self._active_workers = 0
        self._retention = retention
        self._retention_lock = Lock()
        self._skip_next_auto_prune = False
        initial_definitions: dict[str, PipelineDefinition] = {}
        if self._definition_store is not None:
            for persisted in self._definition_store.list_definitions():
                initial_definitions[persisted.name] = persisted
        if definitions:
            for definition in definitions:
                initial_definitions[definition.name] = definition
        for definition in initial_definitions.values():
            stored = self._prepare_definition(definition)
            self._definitions[definition.name] = stored

    def register(self, definition: PipelineDefinition) -> None:
        stored = self._prepare_definition(definition)
        with self._lock:
            if definition.name in self._definitions:
                msg = f"pipeline '{definition.name}' is already registered"
                raise ValueError(msg)
            self._definitions[definition.name] = stored
            definition_store = self._definition_store
        if definition_store is not None:
            definition_store.save(stored)

    def upsert(self, definition: PipelineDefinition) -> bool:
        stored = self._prepare_definition(definition)
        with self._lock:
            created = definition.name not in self._definitions
            self._definitions[definition.name] = stored
            definition_store = self._definition_store
        if definition_store is not None:
            definition_store.save(stored)
        return created

    def deregister(self, name: str) -> None:
        with self._lock:
            try:
                del self._definitions[name]
            except KeyError as exc:
                msg = f"pipeline '{name}' is not registered"
                raise KeyError(msg) from exc
            definition_store = self._definition_store
        if definition_store is not None:
            definition_store.remove(name)

    def list_pipelines(self) -> list[PipelineDefinition]:
        with self._lock:
            definitions = list(self._definitions.values())
        return sorted(definitions, key=lambda item: item.name)

    def get_pipeline(self, name: str) -> PipelineDefinition:
        with self._lock:
            try:
                return self._definitions[name]
            except KeyError as exc:  # pragma: no cover - defensive guard
                msg = f"pipeline '{name}' is not registered"
                raise KeyError(msg) from exc

    def _prepare_definition(self, definition: PipelineDefinition) -> PipelineDefinition:
        resolved = self._executor.resolve_pipeline(definition.pipeline)
        return replace(definition, pipeline=resolved)

    def trigger_run(
        self,
        pipeline_name: str,
        *,
        parameters: Mapping[str, Any] | None = None,
        submitted_by: str | None = None,
        roles: Iterable[str] | None = None,
    ) -> PipelineRun:
        definition = self.get_pipeline(pipeline_name)
        if not definition.enabled:
            msg = f"pipeline '{pipeline_name}' is disabled"
            raise ValueError(msg)
        parameters = definition.resolve_parameters(parameters)
        definition_snapshot = definition.serialise()
        run_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        role_values: tuple[str, ...]
        if roles is None:
            role_values = ()
        else:
            role_values = tuple(str(role) for role in roles)
        run = PipelineRun(
            run_id=run_id,
            pipeline=definition.name,
            status="queued",
            created_at=now,
            updated_at=now,
            parameters=parameters,
            definition_snapshot=definition_snapshot,
            submitted_by=submitted_by,
            roles=role_values,
        )
        initial_event = PipelineRunEvent(
            event_id=None,
            run_id=run_id,
            pipeline=definition.name,
            status="queued",
            timestamp=run.created_at,
            parameters=parameters,
        )
        self._store.create_run(run, initial_event)
        future = self._submit_run(
            definition=definition, run_id=run_id, parameters=parameters
        )
        self._register_future(future)

        return self._store.get_run(run_id)

    def rerun(
        self,
        run_id: str,
        *,
        overrides: Mapping[str, Any] | None = None,
        submitted_by: str | None = None,
        roles: Iterable[str] | None = None,
    ) -> PipelineRun:
        original = self.get_run(run_id)
        snapshot = original.definition_snapshot
        if not snapshot:
            msg = f"pipeline run '{run_id}' is missing a definition snapshot"
            raise ValueError(msg)
        try:
            definition = pipeline_definition_from_serialised(snapshot)
        except (TypeError, ValueError) as exc:
            msg = f"pipeline run '{run_id}' has an invalid definition snapshot"
            raise ValueError(msg) from exc

        definition = self._prepare_definition(definition)

        merged_parameters: dict[str, Any] = dict(original.parameters)
        if overrides:
            merged_parameters.update(overrides)
        parameters = definition.resolve_parameters(merged_parameters)

        new_run_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        role_values: tuple[str, ...]
        if roles is None:
            role_values = original.roles
        else:
            role_values = tuple(str(role) for role in roles)
        submitted_by_value = (
            submitted_by if submitted_by is not None else original.submitted_by
        )

        run = PipelineRun(
            run_id=new_run_id,
            pipeline=definition.name,
            status="queued",
            created_at=now,
            updated_at=now,
            parameters=parameters,
            definition_snapshot=definition.serialise(),
            submitted_by=submitted_by_value,
            roles=role_values,
        )
        initial_event = PipelineRunEvent(
            event_id=None,
            run_id=new_run_id,
            pipeline=definition.name,
            status="queued",
            timestamp=run.created_at,
            parameters=parameters,
        )

        self._store.create_run(run, initial_event)
        future = self._submit_run(
            definition=definition, run_id=new_run_id, parameters=parameters
        )
        self._register_future(future)

        return self._store.get_run(new_run_id)

    def set_enabled(self, name: str, enabled: bool) -> PipelineDefinition:
        updated_definition: PipelineDefinition
        with self._lock:
            try:
                current = self._definitions[name]
            except KeyError as exc:
                msg = f"pipeline '{name}' is not registered"
                raise KeyError(msg) from exc
            if current.enabled == enabled:
                return current
            updated_definition = replace(current, enabled=bool(enabled))
            self._definitions[name] = updated_definition
            definition_store = self._definition_store
        if definition_store is not None:
            definition_store.save(updated_definition)
        return updated_definition

    def _submit_run(
        self,
        *,
        definition: PipelineDefinition,
        run_id: str,
        parameters: Mapping[str, Any],
    ) -> Future[None]:
        if self._shutdown:
            msg = "pipeline orchestrator has been shut down"
            raise RuntimeError(msg)

        def _runner() -> None:
            self._increment_active_workers()
            try:
                self._append_event(run_id, "running")
                try:
                    self._executor.execute(
                        definition.pipeline,
                        parameters=parameters,
                        emit=self._build_step_emitter(
                            run_id,
                            pipeline=definition.pipeline,
                            parameters=parameters,
                        ),
                    )
                except Exception as exc:
                    failure_payload = _serialise_exception(exc)
                    self._append_event(
                        run_id,
                        "failed",
                        parameters=failure_payload,
                    )
                else:
                    self._append_event(run_id, "succeeded")
            finally:
                self._decrement_active_workers()

        future = self._worker_pool.submit(_runner)

        if self._retention is not None:

            def _trigger_prune(_: Future[None]) -> None:
                try:
                    self._schedule_retention_prune()
                except Exception:  # pragma: no cover - defensive guard
                    logger.exception("failed to schedule pipeline retention prune")

            future.add_done_callback(_trigger_prune)

        return future

    def _register_future(self, future: Future[None]) -> None:
        def _cleanup(completed: Future[None]) -> None:
            with self._lock:
                self._pending.discard(completed)

        with self._lock:
            self._pending.add(future)
        future.add_done_callback(_cleanup)

    def worker_pool_metrics(self) -> WorkerPoolMetrics:
        """Return the current worker utilisation and prune completed runs."""

        with self._lock:
            active_futures = {future for future in self._pending if not future.done()}
            self._pending = active_futures
            active_workers = self._active_workers

        return WorkerPoolMetrics(
            max_workers=self._max_workers, active_workers=active_workers
        )

    def _increment_active_workers(self) -> None:
        with self._lock:
            self._active_workers += 1

    def _decrement_active_workers(self) -> None:
        with self._lock:
            self._active_workers = max(0, self._active_workers - 1)

    def _schedule_retention_prune(self) -> None:
        policy = self._retention
        if policy is None or not policy.configured:
            return

        with self._retention_lock:
            if self._skip_next_auto_prune:
                self._skip_next_auto_prune = False
                return

        def _run_prune() -> None:
            try:
                self.prune_history()
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("pipeline retention prune failed")

        try:
            self._worker_pool.submit(_run_prune)
        except RuntimeError:  # pragma: no cover - shutdown race
            logger.debug("worker pool unavailable; skipping retention prune")

    def shutdown(self, *, wait: bool = True) -> None:
        if not self._shutdown:
            self._shutdown = True
            self._worker_pool.shutdown(wait=wait)
            with self._lock:
                self._pending.clear()
                self._active_workers = 0
        self._store.close()

    @staticmethod
    def _determine_max_workers(pool: ThreadPoolExecutor) -> int | None:
        value = getattr(pool, "_max_workers", None)
        if isinstance(value, int):
            return value
        return None

    def _build_step_emitter(
        self,
        run_id: str,
        *,
        pipeline: Pipeline,
        parameters: Mapping[str, Any],
    ) -> pipeline_executor.StepEventEmitter:
        starts: dict[str, list[datetime]] = {}
        lock = Lock()
        pipeline_metadata = dict(pipeline.metadata)
        step_metadata = {step.name: dict(step.metadata) for step in pipeline.steps}
        resolved_parameters = dict(parameters)

        def emit(
            status: str,
            *,
            step: pipeline_executor.ExecutedStep,
            event: pipeline_executor.StepTriggerEvent | None = None,
            error: Exception | None = None,
            context: pipeline_executor.StepExecutionContext | None = None,
        ) -> pipeline_executor.StepExecutionContext | None:
            payload: dict[str, Any] = {"step": step.name}
            now = datetime.now(timezone.utc)

            if status == "step_started":
                started_at = now
                payload["started_at"] = started_at.isoformat()
                with lock:
                    starts.setdefault(step.name, []).append(started_at)
                metadata = {
                    "pipeline": dict(pipeline_metadata),
                    "step": dict(step_metadata.get(step.name, {})),
                }
                context = pipeline_executor.StepExecutionContext(
                    run_id=run_id,
                    pipeline_name=pipeline.name,
                    step_name=step.name,
                    metadata=metadata,
                    parameters=dict(resolved_parameters),
                )
            elif status in {"step_succeeded", "step_failed"}:
                with lock:
                    stack = starts.get(step.name)
                    started_at = stack.pop() if stack else None  # type: ignore[assignment]
                    if stack is not None and not stack:
                        starts.pop(step.name, None)
                if started_at is None:
                    started_at = now
                finished_at = now
                duration_ms = max(
                    int((finished_at - started_at).total_seconds() * 1000), 0
                )
                payload.update(
                    {
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "duration_ms": duration_ms,
                    }
                )

            if event is not None:
                payload["event"] = {
                    "name": event.name,
                    "payload": dict(event.payload),
                }
            if error is not None:
                if isinstance(error, pipeline_executor.PipelineTimeoutError):
                    payload["timeout"] = error.describe_timeout()
                payload.update(_serialise_exception(error))
            self._append_event(run_id, status, parameters=payload)
            return context

        return emit

    def _append_event(
        self,
        run_id: str,
        status: str,
        *,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        timestamp = datetime.now(timezone.utc)
        parameters = dict(parameters or {})
        run_status: str | None
        if status in {"queued", "running", "succeeded", "failed"}:
            run_status = status
        elif status == "step_failed":
            run_status = "failed"
        else:
            run_status = None
        self._store.append_event(
            run_id,
            status=status,
            timestamp=timestamp,
            parameters=parameters,
            run_status=run_status,
        )

    def get_run(self, run_id: str) -> PipelineRun:
        try:
            return self._store.get_run(run_id)
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: datetime | None = None,
        before_id: str | None = None,
        before_created_at: datetime | None = None,
        submitted_by: str | None = None,
        role: str | None = None,
    ) -> PipelineRunPage:
        return self._store.list_runs(
            pipeline=pipeline,
            status=status,
            limit=limit,
            since=since,
            before_id=before_id,
            before_created_at=before_created_at,
            submitted_by=submitted_by,
            role=role,
        )

    def aggregate_runs(
        self,
        *,
        since: datetime | None = None,
        include_durations: bool = False,
        pipeline: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        return self._store.aggregate_runs(
            since=since,
            include_durations=include_durations,
            pipeline=pipeline,
        )

    def iter_run_events(self, run_id: str) -> Iterator[PipelineRunEvent]:
        try:
            return self._store.iter_run_events(run_id)
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def watch_run_events(
        self,
        run_id: str,
        *,
        after_event_id: int | None = None,
        since_timestamp: datetime | None = None,
    ) -> AsyncIterator[PipelineRunEvent]:
        try:
            return self._store.watch_run_events(
                run_id,
                after_event_id=after_event_id,
                since_timestamp=since_timestamp,
            )
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def serialise_run(self, run_id: str) -> Mapping[str, Any]:
        run = self.get_run(run_id)
        return run.serialise()

    def serialise_run_events(self, run_id: str) -> list[Mapping[str, Any]]:
        return [event.serialise() for event in self.iter_run_events(run_id)]

    @property
    def retention_policy(self) -> PipelineRetentionPolicy | None:
        return self._retention

    def prune_history(
        self,
        *,
        max_age: timedelta | None = None,
        max_runs: int | None = None,
        now: datetime | None = None,
    ) -> PipelinePruneResult:
        policy = self._retention
        use_policy_defaults = (
            max_age is None and max_runs is None and policy is not None
        )

        with self._retention_lock:
            if use_policy_defaults:
                self._skip_next_auto_prune = False
            elif max_age is not None or max_runs is not None:
                self._skip_next_auto_prune = True

        max_runs_per_pipeline: Mapping[str, int] | None = None
        if use_policy_defaults and policy is not None:
            max_age = policy.max_age
            max_runs = policy.max_runs
            max_runs_per_pipeline = policy.max_runs_per_pipeline
        elif policy is not None:
            max_runs_per_pipeline = policy.max_runs_per_pipeline

        return self._store.prune(
            max_age=max_age,
            max_runs=max_runs,
            now=now,
            max_runs_per_pipeline=max_runs_per_pipeline,
        )


_default_orchestrator: PipelineOrchestrator | None = None


def get_pipeline_orchestrator(
    *,
    storage: PipelineRunStore | None = None,
    storage_config: Mapping[str, Any] | None = None,
    definition_store: PipelineDefinitionStore | None = None,
) -> PipelineOrchestrator:
    global _default_orchestrator
    if _default_orchestrator is None:
        if (
            storage is not None or definition_store is not None
        ) and storage_config is not None:
            msg = "provide either explicit stores or configuration, not both"
            raise ValueError(msg)
        retention: PipelineRetentionPolicy | None = None
        if storage is None and storage_config is not None:
            if any(key in storage_config for key in ("database", "path")):
                storage = PipelineRunStore.from_config(storage_config)
            retention = _retention_policy_from_storage(storage_config)
            if definition_store is None:
                definition_store = _definition_store_from_storage(storage_config)
        _default_orchestrator = PipelineOrchestrator(
            store=storage, retention=retention, definition_store=definition_store
        )
    elif (
        storage is not None
        or storage_config is not None
        or definition_store is not None
    ):
        msg = (
            "pipeline orchestrator is already configured; "
            "reset it with set_pipeline_orchestrator(None) before supplying storage"
        )
        raise RuntimeError(msg)
    return _default_orchestrator


def set_pipeline_orchestrator(orchestrator: PipelineOrchestrator | None) -> None:
    global _default_orchestrator
    if _default_orchestrator is not None and _default_orchestrator is not orchestrator:
        previous = _default_orchestrator
        previous.shutdown()
        previous._store.close()
    _default_orchestrator = orchestrator


def pipeline_definition_from_profile_entry(
    name: str, config: Mapping[str, Any]
) -> PipelineDefinition:
    """Return a pipeline definition derived from profile configuration."""

    pipeline_config = dict(config)
    pipeline_config.setdefault("name", name)
    pipeline = pipeline_from_config(pipeline_config)

    metadata = pipeline.metadata or {}

    def _coerce_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    display_name = _coerce_optional_str(
        config.get("display_name", metadata.get("display_name"))
    )
    description = _coerce_optional_str(
        config.get("description", metadata.get("description"))
    )

    parameters = _parse_parameter_definitions(
        cast(Mapping[str, Any] | None, config.get("parameters")),
        location=f"pipeline '{name}'",
    )

    version = _coerce_optional_str(config.get("version", metadata.get("version")))

    enabled = config.get("enabled")
    is_enabled = _coerce_enabled_flag(name, enabled) if enabled is not None else True

    return PipelineDefinition(
        name=pipeline.name,
        pipeline=pipeline,
        display_name=display_name,
        description=description,
        parameters=parameters,
        version=version,
        enabled=is_enabled,
    )


def pipeline_definition_from_serialised(
    payload: Mapping[str, Any],
) -> PipelineDefinition:
    """Recreate a :class:`PipelineDefinition` from persisted payload data."""

    if not isinstance(payload, Mapping):
        msg = "persisted pipeline definition must be a mapping"
        raise TypeError(msg)
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        msg = "persisted pipeline definition missing 'name'"
        raise ValueError(msg)
    return pipeline_definition_from_profile_entry(name, dict(payload))


def _retention_policy_from_storage(
    storage_config: Mapping[str, Any],
) -> PipelineRetentionPolicy | None:
    retention_config = storage_config.get("retention")
    if retention_config is None:
        return None
    if not isinstance(retention_config, Mapping):
        msg = "pipeline.storage.retention must be a mapping"
        raise ValueError(msg)
    retention_mapping = cast(Mapping[str, Any], retention_config)
    return PipelineRetentionPolicy.from_mapping(retention_mapping)


def _definition_store_from_storage(
    storage_config: Mapping[str, Any],
) -> PipelineDefinitionStore | None:
    raw_path = storage_config.get("definitions") or storage_config.get(
        "definitions_path"
    )
    if raw_path is None:
        return None
    if isinstance(raw_path, Path):
        path_value: Path | str = raw_path
    else:
        text = str(raw_path).strip()
        if not text:
            msg = "pipeline.storage.definitions must be a non-empty path"
            raise ValueError(msg)
        path_value = text
    return PipelineDefinitionStore(path=path_value)


def pipeline_definitions_from_profile(
    profile: ProfileContext,
) -> tuple[PipelineDefinition, ...]:
    """Build pipeline definitions from a loaded profile context."""

    return tuple(
        pipeline_definition_from_profile_entry(name, config)
        for name, config in sorted(profile.pipelines.items())
    )


def configure_orchestrator_from_profile(
    profile: ProfileContext,
    *,
    storage_config: Mapping[str, Any] | None = None,
    orchestrator_factory: Callable[..., PipelineOrchestrator] | None = None,
) -> PipelineOrchestrator:
    """Initialise the shared orchestrator with definitions from *profile*.

    When a storage configuration mapping is supplied the orchestrator persists
    pipeline run history using :class:`PipelineRunStore`.
    """

    definitions = pipeline_definitions_from_profile(profile)
    effective_storage = storage_config or profile.pipeline_storage
    retention = None
    store = None
    definition_store = None
    if effective_storage:
        retention = _retention_policy_from_storage(effective_storage)
        if any(key in effective_storage for key in ("database", "path")):
            store = PipelineRunStore.from_config(effective_storage)
        definition_store = _definition_store_from_storage(effective_storage)

    if orchestrator_factory is None:
        orchestrator_factory = PipelineOrchestrator

    raw_storage_max_workers = None
    if effective_storage:
        raw_storage_max_workers = effective_storage.get("max_workers")

    if raw_storage_max_workers is not None:
        try:
            storage_max_workers = int(raw_storage_max_workers)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError("pipeline.storage.max_workers must be an integer") from exc
        if storage_max_workers < 1:
            raise ValueError("pipeline.storage.max_workers must be at least 1")
        max_workers = storage_max_workers
    else:
        max_workers = max(1, profile.pipeline_workers_max)

    executor = pipeline_executor.PipelineExecutor(
        event_max_workers=profile.pipeline_executor_event_max_workers,
        step_timeout=profile.pipeline_executor_step_timeout,
        run_timeout=profile.pipeline_executor_run_timeout,
    )

    orchestrator = orchestrator_factory(
        definitions,
        store=store,
        retention=retention,
        definition_store=definition_store,
        max_workers=max_workers,
        executor=executor,
    )
    set_pipeline_orchestrator(orchestrator)
    return orchestrator


__all__ = [
    "ParameterDefinition",
    "PipelineDefinition",
    "WorkerPoolMetrics",
    "PipelineDefinitionStore",
    "PipelineOrchestrator",
    "PipelineRun",
    "PipelineRunEvent",
    "PipelineRunStore",
    "PipelineRetentionPolicy",
    "PipelinePruneResult",
    "get_pipeline_orchestrator",
    "set_pipeline_orchestrator",
    "pipeline_definition_from_profile_entry",
    "pipeline_definition_from_serialised",
    "pipeline_definitions_from_profile",
    "configure_orchestrator_from_profile",
]
