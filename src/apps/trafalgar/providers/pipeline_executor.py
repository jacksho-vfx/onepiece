"""Helpers for executing OnePiece pipelines within the Trafalgar stack."""

from __future__ import annotations

import asyncio
import inspect
from collections import deque
from collections.abc import AsyncIterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Deque, Iterable, Mapping, Protocol

from libraries.pipeline.factories import resolve_provider
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy
from libraries.pipeline import plugins

PROVIDER_REFERENCE_METADATA_KEY = "__provider_reference__"


@dataclass(slots=True)
class StepTriggerEvent:
    """Event emitted by a pipeline step and used to trigger event-driven steps."""

    name: str
    payload: Mapping[str, Any]


@dataclass(slots=True)
class QueuedEvent:
    """Internal representation of events waiting to trigger steps."""

    event: StepTriggerEvent
    delivered_steps: set[str] = field(default_factory=set)


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
        return Pipeline(
            name=pipeline.name, steps=resolved_steps, metadata=pipeline.metadata
        )

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
        events: Deque[QueuedEvent] = deque()

        sequential_steps = [
            step for step in pipeline.steps if step.trigger.is_sequential
        ]
        dependencies: dict[str, set[str]] = {
            step.name: set(step.trigger.depends_on) for step in sequential_steps
        }

        submitted: set[str] = set()
        inflight: dict[Future[list[StepTriggerEvent]], PipelineStep] = {}

        def schedule_ready_steps() -> None:
            for step in sequential_steps:
                if step.name in submitted:
                    continue
                if not dependencies[step.name].issubset(completed_steps):
                    continue
                submitted.add(step.name)
                future = executor.submit(
                    self._execute_sequential_step,
                    step,
                    parameters=parameters,  # type: ignore[arg-type]
                    emit=emit,
                )
                inflight[future] = step

        if sequential_steps:
            max_workers = max(1, min(len(sequential_steps), 32))
        else:
            max_workers = 1

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            schedule_ready_steps()

            while inflight:
                done, _ = wait(tuple(inflight.keys()), return_when=FIRST_COMPLETED)
                for future in done:
                    step = inflight.pop(future)
                    try:
                        emitted_events = future.result()
                    except Exception:
                        for pending_future in list(inflight):
                            pending_future.cancel()
                        raise

                    completed_steps.add(step.name)
                    self._extend_event_queue(events, emitted_events)
                    self._process_event_queue(
                        pipeline,
                        queue=events,
                        completed_steps=completed_steps,
                        parameters=parameters,
                        emit=emit,
                    )
                    schedule_ready_steps()

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
        provider_reference: str | None = None

        if isinstance(provider, str) and provider in self._step_factories:
            provider_reference = provider
            candidate = self._step_factories[provider](step.config)
            if isinstance(candidate, PipelineStep):
                produced_step = candidate
                provider = candidate.provider
            else:
                provider = candidate
        elif isinstance(provider, str):
            provider_reference = provider

        resolved = resolve_provider(provider)
        if not callable(resolved):
            msg = f"pipeline step '{step.name}' provider '{provider!r}' is not callable"
            raise TypeError(msg)

        base = produced_step or step
        if produced_step is not None and produced_step.name != step.name:
            base = replace(base, name=step.name)

        if provider_reference is not None:
            metadata = dict(base.metadata)
            metadata.setdefault(PROVIDER_REFERENCE_METADATA_KEY, provider_reference)
            base = replace(base, metadata=metadata)

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
            result = provider(parameters)
        else:
            result = provider(event, parameters)

        return self._resolve_async_value(result)

    def _normalise_events(self, result: Any) -> Iterable[StepTriggerEvent]:
        if result is None:
            return []
        result = self._resolve_async_value(result)
        if isinstance(result, StepTriggerEvent):
            return [result]
        if isinstance(result, tuple) and len(result) == 2:
            name, payload = result
            return [
                StepTriggerEvent(name=str(name), payload=self._ensure_mapping(payload))
            ]
        if isinstance(result, Mapping):
            if "events" in result:
                return list(self._normalise_events(result["events"]))
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

    def _extend_event_queue(
        self, queue: Deque[QueuedEvent], events: Iterable[StepTriggerEvent]
    ) -> None:
        for event in events:
            queue.append(QueuedEvent(event=event))

    def _execute_sequential_step(
        self,
        step: PipelineStep,
        *,
        parameters: Mapping[str, Any],
        emit: StepEventEmitter,
    ) -> list[StepTriggerEvent]:
        executed_step = ExecutedStep(name=step.name)
        emit("step_started", step=executed_step)
        try:
            result = self._call_provider(step, parameters=parameters)
        except Exception as exc:  # pragma: no cover - defensive guard
            emit("step_failed", step=executed_step, error=exc)
            raise
        emit("step_succeeded", step=executed_step)
        return list(self._normalise_events(result))

    def _process_event_queue(
        self,
        pipeline: Pipeline,
        *,
        queue: Deque[QueuedEvent],
        completed_steps: set[str],
        parameters: Mapping[str, Any],
        emit: StepEventEmitter,
    ) -> None:
        while queue:
            retry: Deque[QueuedEvent] = deque()
            any_delivered = False

            while queue:
                queued_event = queue.popleft()
                event = queued_event.event
                delivered = False
                should_retry = False
                matched = False
                for step in pipeline.steps:
                    if not step.trigger.is_event_driven:
                        continue
                    if not self._event_matches(step.trigger, event):
                        continue
                    matched = True
                    if step.name in queued_event.delivered_steps:
                        continue
                    if not self._dependencies_satisfied(step.trigger, completed_steps):
                        should_retry = True
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
                    queued_event.delivered_steps.add(step.name)
                    completed_steps.add(step.name)
                    delivered = True
                    any_delivered = True
                    self._extend_event_queue(queue, self._normalise_events(result))

                if should_retry:
                    retry.append(queued_event)
                elif not delivered and not matched:
                    continue

            if retry:
                queue.extend(retry)
                if any_delivered:
                    continue
            break

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

    def _resolve_async_value(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return self._run_awaitable(value)
        if isinstance(value, AsyncIterable):
            return self._run_awaitable(self._collect_async_iterable(value))
        return value

    async def _collect_async_iterable(self, iterable: AsyncIterable[Any]) -> list[Any]:
        items: list[Any] = []
        async for item in iterable:
            items.append(item)
        return items

    def _run_awaitable(self, awaitable: Any) -> Any:
        """Execute *awaitable* to completion in a dedicated event loop."""

        if asyncio.isfuture(awaitable) and awaitable.done():
            return awaitable.result()

        loop = asyncio.new_event_loop()
        try:
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(awaitable)
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                finally:
                    asyncio.set_event_loop(None)
        finally:
            loop.close()
