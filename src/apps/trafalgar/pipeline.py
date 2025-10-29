"""Pipeline orchestration helpers shared across Trafalgar services."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterable, Iterator, Mapping

import uuid

from apps.onepiece.config import ProfileContext
from apps.trafalgar.providers import pipeline_executor
from libraries.pipeline.factories import pipeline_from_config
from libraries.pipeline.models import Pipeline


@dataclass(slots=True)
class PipelineDefinition:
    """A lightweight description of a runnable pipeline."""

    name: str
    pipeline: Pipeline
    display_name: str | None = None
    description: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

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
            object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }


@dataclass(slots=True)
class PipelineRun:
    """Metadata describing a pipeline run returned by the orchestrator."""

    run_id: str
    pipeline: str
    status: str
    created_at: datetime
    updated_at: datetime
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        return {
            "id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "parameters": dict(self.parameters),
        }


@dataclass(slots=True)
class PipelineRunEvent:
    """A single status update emitted for a pipeline run."""

    run_id: str
    pipeline: str
    status: str
    timestamp: datetime
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        return {
            "id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "parameters": dict(self.parameters),
        }


class PipelineOrchestrator:
    """In-memory orchestrator used by the Trafalgar tooling layer."""

    def __init__(
        self,
        definitions: Iterable[PipelineDefinition] | None = None,
        *,
        executor: pipeline_executor.PipelineExecutor | None = None,
    ) -> None:
        self._definitions: dict[str, PipelineDefinition] = {}
        self._runs: dict[str, tuple[PipelineRun, list[PipelineRunEvent]]] = {}
        self._lock = Lock()
        self._executor = executor or pipeline_executor.PipelineExecutor()
        if definitions:
            for definition in definitions:
                self.register(definition)

    def register(self, definition: PipelineDefinition) -> None:
        if definition.name in self._definitions:
            msg = f"pipeline '{definition.name}' is already registered"
            raise ValueError(msg)
        resolved = self._executor.resolve_pipeline(definition.pipeline)
        stored = replace(definition, pipeline=resolved)
        self._definitions[definition.name] = stored

    def list_pipelines(self) -> list[PipelineDefinition]:
        return sorted(self._definitions.values(), key=lambda item: item.name)

    def get_pipeline(self, name: str) -> PipelineDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:  # pragma: no cover - defensive guard
            msg = f"pipeline '{name}' is not registered"
            raise KeyError(msg) from exc

    def trigger_run(
        self, pipeline_name: str, *, parameters: Mapping[str, Any] | None = None
    ) -> PipelineRun:
        parameters = dict(parameters or {})
        definition = self.get_pipeline(pipeline_name)
        run_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        run = PipelineRun(
            run_id=run_id,
            pipeline=definition.name,
            status="queued",
            created_at=now,
            updated_at=now,
            parameters=parameters,
        )
        with self._lock:
            self._runs[run_id] = (
                run,
                [
                    PipelineRunEvent(
                        run_id=run_id,
                        pipeline=definition.name,
                        status="queued",
                        timestamp=run.created_at,
                        parameters=parameters,
                    )
                ],
            )

        self._append_event(run_id, "running")

        try:
            self._executor.execute(
                definition.pipeline,
                parameters=parameters,
                emit=self._build_step_emitter(run_id),
            )
        except Exception as exc:
            self._append_event(
                run_id,
                "failed",
                parameters={"error": str(exc)},
            )
        else:
            self._append_event(run_id, "succeeded")

        return self.get_run(run_id)

    def _build_step_emitter(self, run_id: str) -> pipeline_executor.StepEventEmitter:
        def emit(
            status: str,
            *,
            step: pipeline_executor.ExecutedStep,
            event: pipeline_executor.StepTriggerEvent | None = None,
            error: Exception | None = None,
        ) -> None:
            payload: dict[str, Any] = {"step": step.name}
            if event is not None:
                payload["event"] = {
                    "name": event.name,
                    "payload": dict(event.payload),
                }
            if error is not None:
                payload["error"] = str(error)
            self._append_event(run_id, status, parameters=payload)

        return emit

    def _append_event(
        self,
        run_id: str,
        status: str,
        *,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            timestamp = datetime.now(timezone.utc)
            parameters = dict(parameters or {})
            run, events = self._runs[run_id]
            event = PipelineRunEvent(
                run_id=run_id,
                pipeline=run.pipeline,
                status=status,
                timestamp=timestamp,
                parameters=parameters,
            )
            events.append(event)
            run.updated_at = timestamp
            if status in {"queued", "running", "succeeded", "failed"}:
                run.status = status
            elif status == "step_failed":
                run.status = "failed"

    def get_run(self, run_id: str) -> PipelineRun:
        try:
            run, _ = self._runs[run_id]
        except KeyError as exc:  # pragma: no cover - defensive guard
            msg = f"run '{run_id}' could not be found"
            raise KeyError(msg) from exc
        return run

    def iter_run_events(self, run_id: str) -> Iterator[PipelineRunEvent]:
        try:
            _, events = self._runs[run_id]
        except KeyError as exc:  # pragma: no cover - defensive guard
            msg = f"run '{run_id}' could not be found"
            raise KeyError(msg) from exc
        return iter(events.copy())

    def serialise_run(self, run_id: str) -> Mapping[str, Any]:
        run = self.get_run(run_id)
        return run.serialise()

    def serialise_run_events(self, run_id: str) -> list[Mapping[str, Any]]:
        return [event.serialise() for event in self.iter_run_events(run_id)]


_default_orchestrator: PipelineOrchestrator | None = None


def get_pipeline_orchestrator() -> PipelineOrchestrator:
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = PipelineOrchestrator()
    return _default_orchestrator


def set_pipeline_orchestrator(orchestrator: PipelineOrchestrator | None) -> None:
    global _default_orchestrator
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

    parameters_raw = config.get("parameters")
    if parameters_raw is None:
        parameters: Mapping[str, Any] = {}
    elif isinstance(parameters_raw, Mapping):
        parameters = dict(parameters_raw)
    else:
        msg = f"pipeline '{name}' parameters must be a mapping"
        raise TypeError(msg)

    return PipelineDefinition(
        name=pipeline.name,
        pipeline=pipeline,
        display_name=display_name,
        description=description,
        parameters=parameters,
    )


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
) -> PipelineOrchestrator:
    """Initialise the shared orchestrator with definitions from *profile*."""

    definitions = pipeline_definitions_from_profile(profile)
    orchestrator = PipelineOrchestrator(definitions)
    set_pipeline_orchestrator(orchestrator)
    return orchestrator


__all__ = [
    "PipelineDefinition",
    "PipelineOrchestrator",
    "PipelineRun",
    "PipelineRunEvent",
    "get_pipeline_orchestrator",
    "set_pipeline_orchestrator",
    "pipeline_definition_from_profile_entry",
    "pipeline_definitions_from_profile",
    "configure_orchestrator_from_profile",
]
