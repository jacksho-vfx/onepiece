"""Tests for the Trafalgar pipeline executor."""

from __future__ import annotations

import threading
import time
from typing import Any, Mapping

import pytest

from apps.trafalgar.providers.pipeline_executor import (
    PipelineExecutor,
    PipelineStepTimeoutError,
    StepExecutionContext,
    StepTriggerEvent,
)
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy


def _capture_events() -> Any:
    events: list[tuple[str, str]] = []

    def emit(status: str, *, step: Any, **_: object) -> None:
        events.append((status, step.name))

    return events, emit


def test_parallel_sequential_steps_execute_concurrently() -> None:
    barrier = threading.Barrier(2)
    call_order: list[tuple[str, str]] = []
    lock = threading.Lock()

    def make_provider(name: str) -> Any:
        def provider(_: dict[str, object]) -> Any:
            with lock:
                call_order.append(("start", name))
            try:
                barrier.wait(timeout=5)
            except (
                threading.BrokenBarrierError
            ) as exc:  # pragma: no cover - defensive guard
                raise AssertionError(
                    "sequential steps did not run in parallel"
                ) from exc
            with lock:
                call_order.append(("finish", name))

        return provider

    pipeline = Pipeline(
        name="parallel",
        steps=[
            PipelineStep(name="alpha", provider=make_provider("alpha")),
            PipelineStep(name="beta", provider=make_provider("beta")),
        ],
    )

    events, emit = _capture_events()
    executor = PipelineExecutor()
    executor.execute(pipeline, parameters={}, emit=emit)

    assert set(call_order[:2]) == {("start", "alpha"), ("start", "beta")}
    assert set(events) >= {
        ("step_started", "alpha"),
        ("step_started", "beta"),
        ("step_succeeded", "alpha"),
        ("step_succeeded", "beta"),
    }


def test_dependency_ordering_respected_for_sequential_steps() -> None:
    finished_first = threading.Event()

    def provider_first(_: dict[str, object]) -> None:
        finished_first.set()

    def provider_second(_: dict[str, object]) -> None:
        assert finished_first.is_set(), "dependent step started before prerequisite"

    pipeline = Pipeline(
        name="ordered",
        steps=[
            PipelineStep(name="first", provider=provider_first),
            PipelineStep(
                name="second",
                provider=provider_second,
                trigger=TriggerPolicy(kind="sequential", depends_on=("first",)),
            ),
        ],
    )

    events, emit = _capture_events()
    executor = PipelineExecutor()
    executor.execute(pipeline, parameters={}, emit=emit)

    first_success = events.index(("step_succeeded", "first"))
    second_start = events.index(("step_started", "second"))
    assert first_success < second_start


def test_event_queue_guard_limits_infinite_event_churn() -> None:
    def source(_: dict[str, object]) -> StepTriggerEvent:
        return StepTriggerEvent(name="loop", payload={})

    def looper(event: StepTriggerEvent, _: dict[str, object]) -> StepTriggerEvent:
        return StepTriggerEvent(name=event.name, payload=event.payload)

    pipeline = Pipeline(
        name="looping",
        steps=[
            PipelineStep(name="source", provider=source),
            PipelineStep(
                name="listener",
                provider=looper,
                trigger=TriggerPolicy(kind="event", event="loop"),
            ),
        ],
    )

    events, emit = _capture_events()
    executor = PipelineExecutor(event_queue_limit=5)

    with pytest.raises(RuntimeError) as excinfo:
        executor.execute(pipeline, parameters={}, emit=emit)

    message = str(excinfo.value)
    assert "infinite event loop" in message


def _make_contextual_emitter(
    run_id: str,
    pipeline: Pipeline,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, StepExecutionContext], Any]:
    contexts: dict[str, StepExecutionContext] = {}

    def emit(
        status: str,
        *,
        step: Any,
        event: StepTriggerEvent | None = None,
        error: Exception | None = None,
        context: StepExecutionContext | None = None,
    ) -> StepExecutionContext | None:
        if status == "step_started":
            step_definition = pipeline.get_step(step.name)
            metadata = {
                "pipeline": dict(pipeline.metadata),
                "step": dict(step_definition.metadata),
            }
            generated = StepExecutionContext(
                run_id=run_id,
                pipeline_name=pipeline.name,
                step_name=step.name,
                metadata=metadata,
                parameters=dict(parameters),
            )
            contexts[step.name] = generated
            return generated
        if context is not None:
            assert context is contexts[step.name]
        return None

    return contexts, emit


def test_sequential_provider_receives_context() -> None:
    parameters = {"colour": "red"}
    pipeline = Pipeline(
        name="contextual",
        metadata={"owner": "luffy"},
        steps=[
            PipelineStep(
                name="alpha",
                provider=lambda context, params: _validate_sequential_context(
                    context,
                    params,
                    expected_run="run-ctx",
                    expected_pipeline="contextual",
                    expected_step="alpha",
                    expected_metadata={
                        "pipeline": {"owner": "luffy"},
                        "step": {"label": "first"},
                    },
                    expected_parameters=parameters,
                ),
                metadata={"label": "first"},
            ),
        ],
    )
    contexts, emit = _make_contextual_emitter("run-ctx", pipeline, parameters)

    executor = PipelineExecutor()
    executor.execute(pipeline, parameters=parameters, emit=emit)

    context = contexts["alpha"]
    assert context.run_id == "run-ctx"
    assert context.metadata["step"] == {"label": "first"}


def test_sequential_provider_accepts_context_only() -> None:
    parameters: dict[str, Any] = {}
    captured: list[StepExecutionContext] = []

    def provider(context: StepExecutionContext) -> None:
        captured.append(context)

    pipeline = Pipeline(
        name="context-only",
        steps=[PipelineStep(name="alpha", provider=provider)],
    )

    contexts, emit = _make_contextual_emitter("run-context", pipeline, parameters)

    executor = PipelineExecutor()
    executor.execute(pipeline, parameters=parameters, emit=emit)

    assert [ctx.step_name for ctx in captured] == ["alpha"]
    assert captured[0] is contexts["alpha"]


def _validate_sequential_context(
    context: StepExecutionContext,
    params: Mapping[str, Any],
    *,
    expected_run: str,
    expected_pipeline: str,
    expected_step: str,
    expected_metadata: Mapping[str, Any],
    expected_parameters: Mapping[str, Any],
) -> None:
    assert context.run_id == expected_run
    assert context.pipeline_name == expected_pipeline
    assert context.step_name == expected_step
    assert context.metadata == expected_metadata
    assert context.parameters == dict(expected_parameters)
    assert params == expected_parameters


def test_event_driven_provider_receives_context() -> None:
    parameters = {"mode": "eventful"}
    events: list[tuple[str, StepExecutionContext]] = []

    def source_provider(
        context: StepExecutionContext, params: Mapping[str, Any]
    ) -> StepTriggerEvent:
        events.append(("source", context))
        assert context.step_name == "source"
        assert params == parameters
        return StepTriggerEvent(name="ready", payload={"value": 1})

    def listener_provider(
        context: StepExecutionContext,
        event: StepTriggerEvent,
        params: Mapping[str, Any],
    ) -> None:
        events.append(("listener", context))
        assert event.name == "ready"
        assert event.payload == {"value": 1}
        assert params == parameters

    pipeline = Pipeline(
        name="eventing",
        metadata={"owner": "nami"},
        steps=[
            PipelineStep(
                name="source",
                provider=source_provider,
                metadata={"label": "source"},
            ),
            PipelineStep(
                name="listener",
                provider=listener_provider,
                metadata={"label": "listener"},
                trigger=TriggerPolicy(kind="event", event="ready"),
            ),
        ],
    )

    contexts, emit = _make_contextual_emitter("run-event", pipeline, parameters)
    executor = PipelineExecutor()
    executor.execute(pipeline, parameters=parameters, emit=emit)

    assert [name for name, _ in events] == ["source", "listener"]
    assert contexts["source"].run_id == "run-event"
    assert contexts["listener"].metadata["step"] == {"label": "listener"}


def test_event_provider_accepts_context_without_parameters() -> None:
    parameters: dict[str, Any] = {}
    recorded: list[tuple[str, StepTriggerEvent]] = []

    def source_provider(_: Mapping[str, Any]) -> StepTriggerEvent:
        return StepTriggerEvent(name="ready", payload={})

    def listener_provider(
        context: StepExecutionContext, event: StepTriggerEvent
    ) -> None:
        recorded.append((context.step_name, event))

    pipeline = Pipeline(
        name="event-context",
        steps=[
            PipelineStep(name="source", provider=source_provider),
            PipelineStep(
                name="listener",
                provider=listener_provider,
                trigger=TriggerPolicy(kind="event", event="ready"),
            ),
        ],
    )

    contexts, emit = _make_contextual_emitter("run-event-ctx", pipeline, parameters)
    executor = PipelineExecutor()
    executor.execute(pipeline, parameters=parameters, emit=emit)

    assert [name for name, _ in recorded] == ["listener"]
    assert recorded[0][1].name == "ready"
    assert contexts["listener"].step_name == "listener"


def test_step_timeout_aborts_stuck_provider() -> None:
    pipeline = Pipeline(
        name="timeout",
        steps=[
            PipelineStep(
                name="slow",
                provider=lambda _: time.sleep(0.2),
            )
        ],
    )
    contexts, base_emit = _make_contextual_emitter("run-timeout", pipeline, {})
    events: list[tuple[str, str, Exception | None]] = []

    def emit(
        status: str,
        *,
        step: Any,
        error: Exception | None = None,
        context: StepExecutionContext | None = None,
        **kwargs: object,
    ) -> StepExecutionContext | None:
        events.append((status, step.name, error))
        return base_emit(
            status,
            step=step,
            error=error,
            context=context,
            **kwargs,
        )

    executor = PipelineExecutor(step_timeout=0.05)
    with pytest.raises(PipelineStepTimeoutError):
        executor.execute(pipeline, parameters={}, emit=emit)

    failures = [event for event in events if event[0] == "step_failed"]
    assert failures, "expected timeout failure event"
    failure_error = failures[0][2]
    assert isinstance(failure_error, PipelineStepTimeoutError)
    assert failure_error.step_name == "slow"
    assert failure_error.scope == "step"
    assert failure_error.timeout_seconds == pytest.approx(0.05, rel=0.2)
