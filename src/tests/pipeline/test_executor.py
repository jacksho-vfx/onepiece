"""Tests for the Trafalgar pipeline executor."""

from __future__ import annotations

import threading

from apps.trafalgar.providers.pipeline_executor import PipelineExecutor
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy


def _capture_events():
    events: list[tuple[str, str]] = []

    def emit(status: str, *, step, **_: object) -> None:
        events.append((status, step.name))

    return events, emit


def test_parallel_sequential_steps_execute_concurrently():
    barrier = threading.Barrier(2)
    call_order: list[tuple[str, str]] = []
    lock = threading.Lock()

    def make_provider(name: str):
        def provider(_: dict[str, object]) -> None:
            with lock:
                call_order.append(("start", name))
            try:
                barrier.wait(timeout=5)
            except threading.BrokenBarrierError as exc:  # pragma: no cover - defensive guard
                raise AssertionError("sequential steps did not run in parallel") from exc
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


def test_dependency_ordering_respected_for_sequential_steps():
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
