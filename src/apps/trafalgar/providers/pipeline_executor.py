"""Helpers for executing OnePiece pipelines within the Trafalgar stack."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import deque
from collections.abc import AsyncIterable
from concurrent.futures import (
    FIRST_COMPLETED,
    Executor,
    Future,
    ThreadPoolExecutor,
    wait,
)
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from itertools import count
from threading import Lock
from typing import Any, Callable, Deque, Iterable, Literal, Mapping, Protocol

from libraries.pipeline.factories import resolve_provider
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy
from libraries.pipeline.registry import build_pipeline_step_factories
from libraries.pipeline.steps import builtin_pipeline_step_factories

PROVIDER_REFERENCE_METADATA_KEY = "__provider_reference__"


@dataclass(slots=True)
class StepExecutionContext:
    """Contextual information provided to pipeline step providers."""

    run_id: str
    pipeline_name: str
    step_name: str
    metadata: Mapping[str, Any]
    parameters: Mapping[str, Any]


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
        context: StepExecutionContext | None = None,
    ) -> StepExecutionContext | None: ...  # pragma: no cover - Protocol definition


@dataclass(slots=True)
class _StepState:
    step: PipelineStep
    token: str
    started_at: float


class _StepContextRegistry:
    """Thread-safe registry mapping step identifiers to contexts."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._contexts: dict[str, StepExecutionContext] = {}

    def register(self, token: str, context: StepExecutionContext) -> None:
        with self._lock:
            self._contexts[token] = context

    def get(self, token: str) -> StepExecutionContext | None:
        with self._lock:
            return self._contexts.get(token)

    def pop(self, token: str) -> StepExecutionContext | None:
        with self._lock:
            return self._contexts.pop(token, None)


class PipelineTimeoutError(TimeoutError):
    """Base class for timeout-related pipeline failures."""

    scope: Literal["step", "run"]

    def __init__(
        self,
        message: str,
        *,
        timeout: float,
        elapsed: float,
        scope: Literal["step", "run"],
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout
        self.elapsed_seconds = elapsed
        self.scope = scope

    def describe_timeout(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "elapsed_seconds": self.elapsed_seconds,
            "scope": self.scope,
        }


class PipelineStepTimeoutError(PipelineTimeoutError):
    """Exception raised when a pipeline step exceeds its allotted time."""

    def __init__(
        self,
        *,
        step_name: str,
        timeout: float,
        elapsed: float,
        scope: Literal["step", "run"] = "step",
    ) -> None:
        message = (
            f"step '{step_name}' exceeded the {scope} timeout "
            f"after {elapsed:.2f}s (limit {timeout:.2f}s)"
        )
        super().__init__(message, timeout=timeout, elapsed=elapsed, scope=scope)
        self.step_name = step_name

    def describe_timeout(self) -> dict[str, Any]:  # pragma: no cover - trivial wrapper
        payload = super().describe_timeout()
        payload["step"] = self.step_name
        return payload


class PipelineRunTimeoutError(PipelineTimeoutError):
    """Exception raised when a pipeline run exceeds its allotted time."""

    def __init__(self, *, timeout: float, elapsed: float) -> None:
        message = (
            f"pipeline exceeded run timeout after {elapsed:.2f}s "
            f"(limit {timeout:.2f}s)"
        )
        super().__init__(message, timeout=timeout, elapsed=elapsed, scope="run")


def _make_token(prefix: str, name: str, counter: Any) -> str:
    return f"{prefix}-{name}-{next(counter)}"


class PipelineExecutor:
    """Execute pipeline steps sequentially and in response to emitted events."""

    def __init__(
        self,
        *,
        step_factories: Mapping[str, Callable[[Mapping[str, Any]], Any]] | None = None,
        event_queue_limit: int | None = 10_000,
        event_max_workers: int | None = None,
        step_timeout: float | int | None = None,
        run_timeout: float | int | None = None,
    ) -> None:
        if step_factories is None:
            step_factories = build_pipeline_step_factories(
                builtin=builtin_pipeline_step_factories()
            )
        self._step_factories: dict[str, Callable[[Mapping[str, Any]], Any]] = dict(
            step_factories
        )
        if event_queue_limit is not None and event_queue_limit <= 0:
            msg = "event_queue_limit must be positive when provided"
            raise ValueError(msg)
        self._event_queue_limit = event_queue_limit
        if event_max_workers is not None and event_max_workers < 1:
            msg = "event_max_workers must be at least 1 when provided"
            raise ValueError(msg)
        self._event_max_workers = event_max_workers
        self._step_timeout = self._coerce_timeout(step_timeout, "step_timeout")
        self._run_timeout = self._coerce_timeout(run_timeout, "run_timeout")

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
        parameters: Mapping[str, Any],
        emit: StepEventEmitter,
    ) -> None:
        """Run *pipeline* and stream step lifecycle events via *emit*."""

        parameters = dict(parameters or {})
        completed_steps: set[str] = set()
        events: Deque[QueuedEvent] = deque()
        processed_events = 0
        context_registry = _StepContextRegistry()
        token_counter = count()
        run_started_at = time.monotonic()
        run_deadline = None
        if self._run_timeout is not None:
            run_deadline = run_started_at + self._run_timeout

        sequential_steps = [
            step for step in pipeline.steps if step.trigger.is_sequential
        ]
        dependencies: dict[str, set[str]] = {
            step.name: set(step.trigger.depends_on) for step in sequential_steps
        }

        submitted: set[str] = set()
        inflight: dict[Future[list[StepTriggerEvent]], _StepState] = {}

        def schedule_ready_steps() -> None:
            for step in sequential_steps:
                if step.name in submitted:
                    continue
                if not dependencies[step.name].issubset(completed_steps):
                    continue
                submitted.add(step.name)
                initial_context = self._build_context(
                    pipeline=pipeline,
                    step=step,
                    parameters=parameters,
                )
                token = _make_token("seq", step.name, token_counter)
                context_registry.register(token, initial_context)
                future = executor.submit(
                    self._execute_sequential_step,
                    pipeline,
                    step,
                    parameters=parameters,  # type: ignore[arg-type]
                    emit=emit,
                    initial_context=initial_context,
                    context_registry=context_registry,
                    context_token=token,
                )
                inflight[future] = _StepState(
                    step=step,
                    token=token,
                    started_at=time.monotonic(),
                )

        if sequential_steps:
            max_workers = max(1, min(len(sequential_steps), 32))
        else:
            max_workers = 1

        with ExitStack() as stack:
            executor = stack.enter_context(ThreadPoolExecutor(max_workers=max_workers))
            if self._event_max_workers is None:
                event_executor: Executor = executor
            else:
                event_executor = stack.enter_context(
                    ThreadPoolExecutor(max_workers=self._event_max_workers)
                )

            schedule_ready_steps()

            try:
                while inflight:
                    done, timed_out, run_timed_out = self._poll_inflight(
                        inflight,
                        run_deadline=run_deadline,
                    )
                    if run_timed_out:
                        self._handle_run_timeout(
                            inflight,
                            context_registry=context_registry,
                            emit=emit,
                            run_started_at=run_started_at,
                        )
                    if timed_out is not None:
                        self._handle_step_timeout(
                            timed_out,
                            inflight,
                            context_registry=context_registry,
                            emit=emit,
                            scope="step",
                        )
                    for future in done:
                        state = inflight.pop(future)
                        try:
                            emitted_events = future.result(timeout=0.0)
                        except Exception:
                            for pending_future in list(inflight):
                                pending_future.cancel()
                            raise

                        context_registry.pop(state.token)
                        completed_steps.add(state.step.name)
                        self._extend_event_queue(events, emitted_events)
                        processed_events = self._process_event_queue(
                            pipeline,
                            queue=events,
                            completed_steps=completed_steps,
                            parameters=parameters,
                            emit=emit,
                            processed_events=processed_events,
                            event_executor=event_executor,
                            context_registry=context_registry,
                            token_factory=lambda step: _make_token(
                                "evt", step.name, token_counter
                            ),
                            run_deadline=run_deadline,
                            run_started_at=run_started_at,
                        )
                        schedule_ready_steps()
            finally:
                for future in list(inflight):
                    future.cancel()

            processed_events = self._process_event_queue(
                pipeline,
                queue=events,
                completed_steps=completed_steps,
                parameters=parameters,
                emit=emit,
                processed_events=processed_events,
                event_executor=event_executor,
                context_registry=context_registry,
                token_factory=lambda step: _make_token("evt", step.name, token_counter),
                run_deadline=run_deadline,
                run_started_at=run_started_at,
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
        context: StepExecutionContext,
        event: StepTriggerEvent | None = None,
    ) -> Any:
        provider = step.provider
        arg_options: tuple[tuple[Any, ...], ...]

        if event is None:
            if self._prefers_context_first(provider):
                arg_options = (
                    (context, parameters),
                    (context,),
                    (parameters,),
                    (),
                )
            else:
                arg_options = (
                    (parameters,),
                    (context, parameters),
                    (context,),
                    (),
                )
        else:
            if self._prefers_context_first(provider):
                arg_options = (
                    (context, event, parameters),
                    (context, event),
                    (context,),
                    (event, parameters),
                    (event,),
                    (parameters,),
                    (),
                )
            else:
                arg_options = (
                    (context, event, parameters),
                    (event, parameters),
                    (event,),
                    (context, event),
                    (context,),
                    (parameters,),
                    (),
                )

        for candidate_args in arg_options:
            if self._supports_arguments(provider, *candidate_args):
                result = provider(*candidate_args)
                return self._resolve_async_value(result)

        msg = (
            f"pipeline step '{step.name}' provider does not accept a supported "
            "signature"
        )
        raise TypeError(msg)

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
        pipeline: Pipeline,
        step: PipelineStep,
        *,
        parameters: Mapping[str, Any],
        emit: StepEventEmitter,
        initial_context: StepExecutionContext | None = None,
        context_registry: _StepContextRegistry | None = None,
        context_token: str | None = None,
    ) -> list[StepTriggerEvent]:
        executed_step = ExecutedStep(name=step.name)
        context = emit(
            "step_started",
            step=executed_step,
            context=initial_context,
        )
        if context is None:
            context = initial_context or self._build_context(
                pipeline=pipeline,
                step=step,
                parameters=parameters,
            )
        if context_registry is not None and context_token is not None:
            context_registry.register(context_token, context)
        try:
            result = self._call_provider(
                step,
                parameters=parameters,
                context=context,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            emit("step_failed", step=executed_step, error=exc, context=context)
            raise
        else:
            emit("step_succeeded", step=executed_step, context=context)
            return list(self._normalise_events(result))
        finally:
            if context_registry is not None and context_token is not None:
                context_registry.pop(context_token)

    def _execute_event_step(
        self,
        pipeline: Pipeline,
        step: PipelineStep,
        *,
        event: StepTriggerEvent,
        parameters: Mapping[str, Any],
        emit: StepEventEmitter,
        initial_context: StepExecutionContext | None = None,
        context_registry: _StepContextRegistry | None = None,
        context_token: str | None = None,
    ) -> list[StepTriggerEvent]:
        executed_step = ExecutedStep(name=step.name)
        context = emit(
            "step_started",
            step=executed_step,
            event=event,
            context=initial_context,
        )
        if context is None:
            context = initial_context or self._build_context(
                pipeline=pipeline,
                step=step,
                parameters=parameters,
            )
        if context_registry is not None and context_token is not None:
            context_registry.register(context_token, context)
        try:
            result = self._call_provider(
                step,
                parameters=parameters,
                context=context,
                event=event,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            emit(
                "step_failed",
                step=executed_step,
                event=event,
                error=exc,
                context=context,
            )
            raise
        else:
            emit(
                "step_succeeded",
                step=executed_step,
                event=event,
                context=context,
            )
            return list(self._normalise_events(result))
        finally:
            if context_registry is not None and context_token is not None:
                context_registry.pop(context_token)

    def _poll_inflight(
        self,
        inflight: Mapping[Future[list[StepTriggerEvent]], _StepState],
        *,
        run_deadline: float | None,
    ) -> tuple[
        set[Future[list[StepTriggerEvent]]],
        Future[list[StepTriggerEvent]] | None,
        bool,
    ]:
        if not inflight:
            return set(), None, False

        now = time.monotonic()
        expired_future: Future[list[StepTriggerEvent]] | None = None
        timeout: float | None = None

        if self._step_timeout is not None:
            for future, state in inflight.items():
                deadline = state.started_at + self._step_timeout
                remaining = deadline - now
                if remaining <= 0:
                    expired_future = future
                    break
                if timeout is None or remaining < timeout:
                    timeout = remaining

        if expired_future is not None:
            return set(), expired_future, False

        if run_deadline is not None:
            run_remaining = run_deadline - now
            if run_remaining <= 0:
                return set(), None, True
            if timeout is None or run_remaining < timeout:
                timeout = max(run_remaining, 0.0)

        if timeout is not None:
            timeout = max(timeout, 0.0)

        done, _ = wait(
            tuple(inflight.keys()), return_when=FIRST_COMPLETED, timeout=timeout
        )
        if done:
            return done, None, False

        now = time.monotonic()
        if run_deadline is not None and now >= run_deadline:
            return set(), None, True
        if self._step_timeout is not None:
            for future, state in inflight.items():
                if now >= state.started_at + self._step_timeout:
                    return set(), future, False
        return set(), None, False

    def _handle_step_timeout(
        self,
        future: Future[list[StepTriggerEvent]],
        inflight: dict[Future[list[StepTriggerEvent]], _StepState],
        *,
        context_registry: _StepContextRegistry,
        emit: StepEventEmitter,
        scope: Literal["step", "run"],
    ) -> None:
        state = inflight.pop(future, None)
        if state is None:
            return
        context = context_registry.pop(state.token)
        timeout_value = self._step_timeout if scope == "step" else self._run_timeout
        assert timeout_value is not None  # enforced by callers
        elapsed = max(time.monotonic() - state.started_at, 0.0)
        error = PipelineStepTimeoutError(
            step_name=state.step.name,
            timeout=timeout_value,
            elapsed=elapsed,
            scope=scope,
        )
        emit(
            "step_failed",
            step=ExecutedStep(name=state.step.name),
            error=error,
            context=context,
        )
        future.cancel()
        raise error

    def _handle_run_timeout(
        self,
        inflight: dict[Future[list[StepTriggerEvent]], _StepState],
        *,
        context_registry: _StepContextRegistry,
        emit: StepEventEmitter,
        run_started_at: float,
    ) -> None:
        if self._run_timeout is None:
            return
        now = time.monotonic()
        error = PipelineRunTimeoutError(
            timeout=self._run_timeout,
            elapsed=max(now - run_started_at, 0.0),
        )
        for future, state in list(inflight.items()):
            context = context_registry.pop(state.token)
            elapsed = max(now - state.started_at, 0.0)
            step_error = PipelineStepTimeoutError(
                step_name=state.step.name,
                timeout=self._run_timeout,
                elapsed=elapsed,
                scope="run",
            )
            emit(
                "step_failed",
                step=ExecutedStep(name=state.step.name),
                error=step_error,
                context=context,
            )
            future.cancel()
        inflight.clear()
        raise error

    @staticmethod
    def _coerce_timeout(value: float | int | None, name: str) -> float | None:
        if value is None:
            return None
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            msg = f"{name} must be a positive number when provided"
            raise ValueError(msg)
        if timeout <= 0:
            msg = f"{name} must be positive when provided"
            raise ValueError(msg)
        return timeout

    def _process_event_queue(
        self,
        pipeline: Pipeline,
        *,
        queue: Deque[QueuedEvent],
        completed_steps: set[str],
        parameters: Mapping[str, Any],
        emit: StepEventEmitter,
        processed_events: int,
        event_executor: Executor,
        context_registry: _StepContextRegistry,
        token_factory: Callable[[PipelineStep], str],
        run_deadline: float | None,
        run_started_at: float,
    ) -> int:
        inflight: dict[Future[list[StepTriggerEvent]], _StepState] = {}

        try:
            while queue or inflight:
                retry: Deque[QueuedEvent] = deque()
                dispatched = False

                while queue:
                    if (
                        self._event_queue_limit is not None
                        and processed_events >= self._event_queue_limit
                    ):
                        msg = (
                            "pipeline emitted too many events without quiescing; "
                            "possible infinite event loop"
                        )
                        raise RuntimeError(msg)
                    queued_event = queue.popleft()
                    processed_events += 1
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
                        if not self._dependencies_satisfied(
                            step.trigger, completed_steps
                        ):
                            should_retry = True
                            continue

                        queued_event.delivered_steps.add(step.name)
                        initial_context = self._build_context(
                            pipeline=pipeline,
                            step=step,
                            parameters=parameters,
                        )
                        token = token_factory(step)
                        context_registry.register(token, initial_context)
                        future = event_executor.submit(
                            self._execute_event_step,
                            pipeline,
                            step,
                            event=event,
                            parameters=parameters,
                            emit=emit,
                            initial_context=initial_context,
                            context_registry=context_registry,
                            context_token=token,
                        )
                        inflight[future] = _StepState(
                            step=step,
                            token=token,
                            started_at=time.monotonic(),
                        )
                        delivered = True
                        dispatched = True

                    if should_retry:
                        retry.append(queued_event)
                    elif not delivered and not matched:
                        continue

                if retry:
                    queue.extend(retry)
                    if dispatched:
                        continue

                if inflight:
                    done, timed_out, run_timed_out = self._poll_inflight(
                        inflight,
                        run_deadline=run_deadline,
                    )
                    if run_timed_out:
                        self._handle_run_timeout(
                            inflight,
                            context_registry=context_registry,
                            emit=emit,
                            run_started_at=run_started_at,
                        )
                    if timed_out is not None:
                        self._handle_step_timeout(
                            timed_out,
                            inflight,
                            context_registry=context_registry,
                            emit=emit,
                            scope="step",
                        )
                    for future in done:
                        state = inflight.pop(future)
                        try:
                            emitted_events = future.result(timeout=0.0)
                        except Exception:
                            for pending in list(inflight):
                                pending.cancel()
                            raise
                        context_registry.pop(state.token)
                        completed_steps.add(state.step.name)
                        self._extend_event_queue(queue, emitted_events)
                    continue

                break
        finally:
            for future in list(inflight):
                future.cancel()
        return processed_events

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

    def _build_context(
        self,
        *,
        pipeline: Pipeline,
        step: PipelineStep,
        parameters: Mapping[str, Any],
        run_id: str | None = None,
    ) -> StepExecutionContext:
        metadata = {
            "pipeline": dict(pipeline.metadata),
            "step": dict(step.metadata),
        }
        return StepExecutionContext(
            run_id=run_id or "",
            pipeline_name=pipeline.name,
            step_name=step.name,
            metadata=metadata,
            parameters=dict(parameters),
        )

    def _supports_arguments(self, provider: Any, *args: Any) -> bool:
        try:
            signature = inspect.signature(provider)
        except (TypeError, ValueError):
            return False
        try:
            signature.bind_partial(*args)
        except TypeError:
            return False
        return True

    def _prefers_context_first(self, provider: Any) -> bool:
        try:
            signature = inspect.signature(provider)
        except (TypeError, ValueError):
            return False

        parameters = list(signature.parameters.values())
        if not parameters:
            return False

        first = parameters[0]
        annotation = first.annotation
        if annotation is not inspect._empty:
            if annotation is StepExecutionContext:
                return True
            if getattr(annotation, "__name__", None) == StepExecutionContext.__name__:
                return True

        name = first.name
        if isinstance(name, str) and name.lower() in {"context", "ctx"}:
            return True

        return False

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
