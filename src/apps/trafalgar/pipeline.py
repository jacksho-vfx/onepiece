"""Pipeline orchestration helpers shared across Trafalgar services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Iterable, Iterator, Mapping

import uuid


@dataclass(slots=True)
class PipelineDefinition:
    """A lightweight description of a runnable pipeline."""

    name: str
    display_name: str | None = None
    description: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        if not self.name:
            msg = "pipeline definitions require a name"
            raise ValueError(msg)
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

    def __init__(self, definitions: Iterable[PipelineDefinition] | None = None) -> None:
        self._definitions: dict[str, PipelineDefinition] = {}
        self._runs: dict[str, tuple[PipelineRun, list[PipelineRunEvent]]] = {}
        self._lock = Lock()
        if definitions:
            for definition in definitions:
                self.register(definition)

    def register(self, definition: PipelineDefinition) -> None:
        if definition.name in self._definitions:
            msg = f"pipeline '{definition.name}' is already registered"
            raise ValueError(msg)
        self._definitions[definition.name] = definition

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
        with self._lock:
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
            events = self._generate_default_events(run)
            final_event = events[-1]
            run.status = final_event.status
            run.updated_at = final_event.timestamp
            self._runs[run_id] = (run, events)
            return run

    def _generate_default_events(self, run: PipelineRun) -> list[PipelineRunEvent]:
        base_timestamp = run.created_at
        statuses = ("queued", "running", "succeeded")
        events: list[PipelineRunEvent] = []
        for index, status in enumerate(statuses):
            timestamp = base_timestamp
            if index:
                # Preserve ordering even if triggered within the same second.
                timestamp = base_timestamp + timedelta(seconds=index)
            events.append(
                PipelineRunEvent(
                    run_id=run.run_id,
                    pipeline=run.pipeline,
                    status=status,
                    timestamp=timestamp,
                    parameters=run.parameters,
                )
            )
        return events

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


__all__ = [
    "PipelineDefinition",
    "PipelineOrchestrator",
    "PipelineRun",
    "PipelineRunEvent",
    "get_pipeline_orchestrator",
    "set_pipeline_orchestrator",
]
