"""Helpers for executing OnePiece pipelines within the Trafalgar stack."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Any, Callable, Deque, Iterable, Mapping, Protocol

from libraries.pipeline.factories import resolve_provider
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy
from libraries.pipeline import plugins


@dataclass(slots=True)
class StepTriggerEvent:
    """Event emitted by a pipeline step and used to trigger event-driven steps."""

    name: str
    payload: Mapping[str, Any]


@dataclass(slots=True)
class ExecutedStep:
    """Wrapper exposing the executed pipeline step for event callbacks."""

    name: str


class StepEventEmitter(Protocol):
    """Signature for callbacks receiving step execution updates."""

    def __call__(
        self,
        status: str,
        *,
        step: ExecutedStep,
        event: StepTriggerEvent | None = None,
        error: Exception | None = None,
    ) -> None: ...  # pragma: no cover - Protocol definition


class PipelineExecutor:
    """Execute pipeline steps sequentially and in response to emitted events."""

    def __init__(
        self,
        *,
        step_factories: Mapping[str, Callable[[Mapping[str, Any]], Any]] | None = None,
    ) -> None:
        if step_factories is None:
            step_factories = plugins.discover_pipeline_step_factories()
        self._step_factories: dict[str, Callable[[Mapping[str, Any]], Any]] = dict(
            step_factories
        )

    def resolve_pipeline(self, pipeline: Pipeline) -> Pipeline:
        """Return a copy of *pipeline* with providers resolved to callables."""

        resolved_steps: list[PipelineStep] = []
        for step in pipeline.steps:
            resolved_steps.append(self._resolve_step(step))
        return Pipeline(name=pipeline.name, steps=resolved_steps, metadata=pipeline.metadata)

    # Public API ---------------------------------------------------------

    def execute(
        self,
        pipeline: Pipeline,
        *,
        parameters: Mapping[str, Any] | None = None,
        emit: StepEventEmitter,
    ) -> None:
        """Run *pipeline* and stream step lifecycle events via *emit*."""

        parameters = dict(parameters or {})
        completed_steps: set[str] = set()
        events: Deque[StepTriggerEvent] = deque()

        for step in pipeline.sequential_order():
            executed_step = ExecutedStep(name=step.name)
            emit("step_started", step=executed_step)
            try:
                result = self._call_provider(step, parameters=parameters)
            except Exception as exc:  # pragma: no cover - defensive guard
                emit("step_failed", step=executed_step, error=exc)
                raise
            emit("step_succeeded", step=executed_step)
            completed_steps.add(step.name)
            events.extend(self._normalise_events(result))

        self._process_event_queue(
            pipeline,
            queue=events,
            completed_steps=completed_steps,
            parameters=parameters,
            emit=emit,
        )

    # Resolution helpers -------------------------------------------------

    def _resolve_step(self, step: PipelineStep) -> PipelineStep:
        provider = step.provider
        produced_step: PipelineStep | None = None

        if isinstance(provider, str) and provider in self._step_factories:
            candidate = self._step_factories[provider](step.config)
            if isinstance(candidate, PipelineStep):
                produced_step = candidate
                provider = candidate.provider
            else:
                provider = candidate

        resolved = resolve_provider(provider)
        if not callable(resolved):
            msg = f"pipeline step '{step.name}' provider '{provider!r}' is not callable"
            raise TypeError(msg)

        base = produced_step or step
        if produced_step is not None and produced_step.name != step.name:
            base = replace(base, name=step.name)
        return replace(base, provider=resolved)

    # Execution helpers --------------------------------------------------

    def _call_provider(
        self,
        step: PipelineStep,
        *,
        parameters: Mapping[str, Any],
        event: StepTriggerEvent | None = None,
    ) -> Any:
        provider = step.provider
        if event is None:
            return provider(parameters)

        return provider(event, parameters)

    def _normalise_events(self, result: Any) -> Iterable[StepTriggerEvent]:
        if result is None:
            return []
        if isinstance(result, StepTriggerEvent):
            return [result]
        if isinstance(result, tuple) and len(result) == 2:
            name, payload = result
            return [StepTriggerEvent(name=str(name), payload=self._ensure_mapping(payload))]
        if isinstance(result, Mapping):
            if "events" in result:
                items = result["events"]
                return list(self._normalise_events(items))
            if "event" in result or "name" in result:
                event_name = str(result.get("event") or result.get("name"))
                payload = self._ensure_mapping(result.get("payload", {}))
                return [StepTriggerEvent(name=event_name, payload=payload)]
            return []
        if isinstance(result, Iterable) and not isinstance(result, (str, bytes)):
            events: list[StepTriggerEvent] = []
            for item in result:
                events.extend(self._normalise_events(item))
            return events
        return []

    def _process_event_queue(
        self,
        pipeline: Pipeline,
        *,
        queue: Deque[StepTriggerEvent],
        completed_steps: set[str],
        parameters: Mapping[str, Any],
        emit: StepEventEmitter,
    ) -> None:
        processed: set[tuple[str, int]] = set()
        event_index = 0

        while queue:
            event = queue.popleft()
            event_index += 1
            for step in pipeline.steps:
                if not step.trigger.is_event_driven:
                    continue
                if not self._dependencies_satisfied(step.trigger, completed_steps):
                    continue
                if not self._event_matches(step.trigger, event):
                    continue
                key = (step.name, event_index)
                if key in processed:
                    continue

                executed_step = ExecutedStep(name=step.name)
                emit("step_started", step=executed_step, event=event)
                try:
                    result = self._call_provider(
                        step,
                        parameters=parameters,
                        event=event,
                    )
                except Exception as exc:  # pragma: no cover - defensive guard
                    emit("step_failed", step=executed_step, event=event, error=exc)
                    raise

                emit("step_succeeded", step=executed_step, event=event)
                processed.add(key)
                completed_steps.add(step.name)
                queue.extend(self._normalise_events(result))

    def _dependencies_satisfied(
        self, trigger: TriggerPolicy, completed_steps: set[str]
    ) -> bool:
        return all(dependency in completed_steps for dependency in trigger.depends_on)

    def _event_matches(self, trigger: TriggerPolicy, event: StepTriggerEvent) -> bool:
        if trigger.event and trigger.event != event.name:
            return False
        for key, expected in trigger.filters.items():
            actual = event.payload.get(key)
            if actual != expected:
                return False
        return True

    def _ensure_mapping(self, payload: Any) -> Mapping[str, Any]:
        if isinstance(payload, Mapping):
            return dict(payload)
        return {"value": payload}
