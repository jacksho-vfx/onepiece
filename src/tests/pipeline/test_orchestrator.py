"""Behavioural tests for the Trafalgar pipeline orchestrator."""

from __future__ import annotations

from queue import Queue
from threading import Barrier, BrokenBarrierError, Event
import time
from typing import Any

# import pytest

from apps.trafalgar.pipeline import PipelineDefinition, PipelineOrchestrator
from apps.trafalgar.providers.pipeline_executor import (
    PipelineExecutor,
    StepTriggerEvent,
)
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy


def _wait_for_completion(
    orchestrator: PipelineOrchestrator, run_id: str, *, timeout: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = orchestrator.get_run(run_id)
        if run.status in {"succeeded", "failed"}:
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for run '{run_id}' to complete")


def test_pipeline_runs_execute_concurrently_with_configured_max_workers() -> None:
    starts: Queue[tuple[int, float]] = Queue()
    release_events: dict[int, Event] = {}

    def _blocking_provider(parameters: dict[str, object]) -> None:
        index = int(parameters["index"])  # type: ignore[call-overload]
        event = release_events.setdefault(index, Event())
        starts.put((index, time.perf_counter()))
        event.wait(timeout=5)

    pipeline = Pipeline(
        name="blocking",
        steps=[PipelineStep(name="wait", provider=_blocking_provider)],
    )
    definition = PipelineDefinition(name="blocking", pipeline=pipeline)
    orchestrator = PipelineOrchestrator((definition,), max_workers=2)

    try:
        first_run = orchestrator.trigger_run("blocking", parameters={"index": 1})
        second_run = orchestrator.trigger_run("blocking", parameters={"index": 2})

        first_started = starts.get(timeout=1.0)
        second_started = starts.get(timeout=1.0)
        assert {first_started[0], second_started[0]} == {1, 2}

        release_events.setdefault(1, Event()).set()
        release_events.setdefault(2, Event()).set()

        _wait_for_completion(orchestrator, first_run.run_id)
        _wait_for_completion(orchestrator, second_run.run_id)
    finally:
        for event in release_events.values():
            event.set()
        orchestrator.shutdown()


def test_event_driven_steps_execute_in_parallel() -> None:
    barrier = Barrier(2)
    starts: Queue[tuple[str, float]] = Queue()
    finishes: Queue[tuple[str, float]] = Queue()

    def source_provider(_: dict[str, object]) -> StepTriggerEvent:
        return StepTriggerEvent(name="asset.ready", payload={})

    def make_listener(name: str) -> Any:
        def provider(event: StepTriggerEvent, _: dict[str, object]) -> None:
            starts.put((name, time.perf_counter()))
            try:
                barrier.wait(timeout=5)
            except BrokenBarrierError as exc:  # pragma: no cover - defensive guard
                raise AssertionError(
                    f"event-driven step '{name}' did not run in parallel"
                ) from exc
            finishes.put((name, time.perf_counter()))

        return provider

    pipeline = Pipeline(
        name="events",
        steps=[
            PipelineStep(name="seed", provider=source_provider),
            PipelineStep(
                name="listener_a",
                provider=make_listener("listener_a"),
                trigger=TriggerPolicy(kind="event", event="asset.ready"),
            ),
            PipelineStep(
                name="listener_b",
                provider=make_listener("listener_b"),
                trigger=TriggerPolicy(kind="event", event="asset.ready"),
            ),
        ],
    )
    definition = PipelineDefinition(name="events", pipeline=pipeline)
    executor = PipelineExecutor(event_max_workers=2)
    orchestrator = PipelineOrchestrator((definition,), executor=executor)

    try:
        run = orchestrator.trigger_run("events", parameters={})
        _wait_for_completion(orchestrator, run.run_id)

        first_start = starts.get(timeout=1.0)
        second_start = starts.get(timeout=1.0)
        assert {first_start[0], second_start[0]} == {"listener_a", "listener_b"}
        assert abs(first_start[1] - second_start[1]) < 0.5

        first_finish = finishes.get(timeout=1.0)
        second_finish = finishes.get(timeout=1.0)
        assert {first_finish[0], second_finish[0]} == {"listener_a", "listener_b"}
    finally:
        orchestrator.shutdown()


# def test_orchestrator_records_timeout_metadata() -> None:
#     pipeline = Pipeline(
#         name="timeout",
#         steps=[
#             PipelineStep(
#                 name="slow",
#                 provider=lambda _: time.sleep(0.2),
#             )
#         ],
#     )
#     definition = PipelineDefinition(name="timeout", pipeline=pipeline)
#     executor = PipelineExecutor(step_timeout=0.05)
#     orchestrator = PipelineOrchestrator((definition,), executor=executor)
#
#     try:
#         run = orchestrator.trigger_run("timeout", parameters={})
#         _wait_for_completion(orchestrator, run.run_id)
#
#         run_record = orchestrator.get_run(run.run_id)
#         assert run_record.status == "failed"
#
#         events = list(orchestrator.iter_run_events(run.run_id))
#         failure_event = next(event for event in events if event.status == "failed")
#         step_failure = next(event for event in events if event.status == "step_failed")
#
#         assert failure_event.parameters.get("error_type") == "PipelineStepTimeoutError"
#         timeout_info = step_failure.parameters.get("timeout")
#         assert timeout_info is not None
#         assert timeout_info["scope"] == "step"
#         assert timeout_info["step"] == "slow"
#         assert timeout_info["timeout_seconds"] == pytest.approx(0.05, rel=0.2)
#     finally:
#         orchestrator.shutdown()


# @pytest.fixture
# def orchestrator(
#     monkeypatch: pytest.MonkeyPatch, tmp_path: Path
# ) -> PipelineOrchestrator:
#     """Return an orchestrator configured with deterministic step factories."""

#     def sequential_factory(
#         config: dict[str, object]
#     ) -> Callable[[dict[str, object]], list[tuple[str, dict[str, object]]]]:
#         def provider(
#             parameters: dict[str, object]
#         ) -> list[tuple[str, dict[str, object]]]:
#             event_payload = {
#                 "department": parameters.get("department", "lighting"),
#                 "shot": parameters.get("shot", "sh010"),
#             }
#             return [("asset.ingested", event_payload)]

#         return provider

#     def event_factory(
#         config: dict[str, object]
#     ) -> Callable[[pipeline_executor.StepTriggerEvent, dict[str, object]], None]:
#         def provider(
#             event: pipeline_executor.StepTriggerEvent, parameters: dict[str, object]
#         ) -> None:
#             _ = (
#                 config,
#                 event,
#                 parameters,
#             )  # pragma: no cover - exercise callable signature

#         return provider

#     monkeypatch.setattr(
#         pipeline_executor.plugins,
#         "discover_pipeline_step_factories",
#         lambda: {"sequential": sequential_factory, "event-listener": event_factory},
#     )

#     store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
#     return PipelineOrchestrator(store=store)


# def _wait_for_run(
#     orchestrator: PipelineOrchestrator,
#     run_id: str,
#     *,
#     status: str,
#     timeout: float = 5.0,
# ) -> PipelineRun:
#     deadline = time.monotonic() + timeout
#     while True:
#         run = orchestrator.get_run(run_id)
#         if run.status == status:
#             return run
#         if time.monotonic() >= deadline:
#             msg = f"timed out waiting for run '{run_id}' to reach status '{status}'"
#             raise AssertionError(msg)
#         time.sleep(0.01)


# def _build_pipeline() -> Pipeline:
#     return Pipeline(
#         name="demo",
#         steps=[
#             PipelineStep(
#                 name="seed",
#                 provider="sequential",
#                 config={"emits": "asset.ingested"},
#             ),
#             PipelineStep(
#                 name="listener",
#                 provider="event-listener",
#                 config={"expects": "asset.ingested"},
#                 trigger=TriggerPolicy(
#                     kind="event",
#                     event="asset.ingested",
#                     filters={"department": "lighting"},
#                     depends_on=("seed",),
#                 ),
#             ),
#         ],
#     )


# def test_orchestrator_emits_step_events(orchestrator: PipelineOrchestrator) -> None:
#     pipeline = _build_pipeline()
#     definition = PipelineDefinition(
#         name="demo",
#         pipeline=pipeline,
#         parameters={
#             "department": ParameterDefinition(default="lighting"),
#             "shot": ParameterDefinition(default="sh010"),
#         },
#     )
#     orchestrator.register(definition)

#     run = orchestrator.trigger_run(
#         "demo", parameters={"department": "lighting", "shot": "sh020"}
#     )
#     assert run.status in {"queued", "running"}

#     run = _wait_for_run(orchestrator, run.run_id, status="succeeded")

#     events = list(orchestrator.iter_run_events(run.run_id))
#     statuses = [event.status for event in events]
#     assert statuses == [
#         "queued",
#         "running",
#         "step_started",
#         "step_succeeded",
#         "step_started",
#         "step_succeeded",
#         "succeeded",
#     ]

#     step_payloads = [
#         event.parameters for event in events if event.status.startswith("step_")
#     ]
#     assert step_payloads[0]["step"] == "seed"
#     assert step_payloads[1]["step"] == "seed"
#     assert step_payloads[2]["step"] == "listener"
#     assert step_payloads[2]["event"]["name"] == "asset.ingested"
#     assert step_payloads[2]["event"]["payload"]["shot"] == "sh020"


# def test_run_serialisation_includes_step_timings(
#     orchestrator: PipelineOrchestrator,
# ) -> None:
#     pipeline = _build_pipeline()
#     definition = PipelineDefinition(
#         name="demo",
#         pipeline=pipeline,
#         parameters={
#             "department": ParameterDefinition(default="lighting"),
#             "shot": ParameterDefinition(default="sh010"),
#         },
#     )
#     orchestrator.register(definition)

#     run = orchestrator.trigger_run("demo")
#     _wait_for_run(orchestrator, run.run_id, status="succeeded")

#     events = orchestrator.serialise_run_events(run.run_id)
#     step_started = [event for event in events if event["status"] == "step_started"]
#     assert step_started, "expected step_started events to be recorded"
#     assert all(
#         "started_at" in event["parameters"] for event in step_started
#     ), "step_started events should include a start timestamp"

#     completed = [
#         event
#         for event in events
#         if event["status"] in {"step_succeeded", "step_failed"}
#     ]
#     assert completed, "expected step completion events to be recorded"
#     assert all(
#         "duration_ms" in event["parameters"] for event in completed
#     ), "step completion events should include a duration"

#     run_payload = orchestrator.serialise_run(run.run_id)
#     timing = run_payload["timing"]
#     assert timing["started_at"] is not None
#     assert timing["finished_at"] is not None
#     assert timing["duration_ms"] is not None

#     started_at = datetime.fromisoformat(timing["started_at"])
#     finished_at = datetime.fromisoformat(timing["finished_at"])
#     calculated_duration = int((finished_at - started_at).total_seconds() * 1000)
#     assert (
#         abs(timing["duration_ms"] - calculated_duration) <= 5
#     ), "run duration should align with recorded timestamps"

#     completed_durations = [
#         int(event["parameters"]["duration_ms"]) for event in completed
#     ]
#     total_completed_duration = sum(completed_durations)
#     assert (
#         timing.get("total_step_duration_ms") == total_completed_duration
#     ), "aggregate step timing should match event totals"

#     step_metrics = run_payload["step_metrics"]
#     assert step_metrics, "expected step metrics to be reported"
#     for name, metrics in step_metrics.items():
#         assert metrics["count"] >= 1
#         assert metrics["last_duration_ms"] is not None
#         matching_events = [
#             event for event in completed if event["parameters"]["step"] == name
#         ]
#         expected_total = sum(
#             int(event["parameters"]["duration_ms"]) for event in matching_events
#         )
#         assert metrics["total_duration_ms"] == expected_total


# def _parameterised_pipeline() -> PipelineDefinition:
#     pipeline = Pipeline(
#         name="parameter-demo",
#         steps=[
#             PipelineStep(
#                 name="prepare",
#                 provider="tests.pipeline:prepare",
#                 config={"emits": "asset.ingested"},
#             )
#         ],
#     )
#     return PipelineDefinition(
#         name=pipeline.name,
#         pipeline=pipeline,
#         parameters={
#             "department": ParameterDefinition(default="lighting"),
#             "shot": ParameterDefinition(required=True),
#             "priority": ParameterDefinition(default="normal"),
#         },
#     )


# def test_trigger_run_merges_defaults(orchestrator: PipelineOrchestrator) -> None:
#     definition = _parameterised_pipeline()
#     orchestrator.register(definition)

#     run = orchestrator.trigger_run(
#         definition.name, parameters={"shot": "sh030", "priority": "rush"}
#     )

#     assert run.parameters == {
#         "department": "lighting",
#         "shot": "sh030",
#         "priority": "rush",
#     }


# def test_trigger_run_rejects_missing_required_parameter(
#     orchestrator: PipelineOrchestrator,
# ) -> None:
#     definition = _parameterised_pipeline()
#     orchestrator.register(definition)

#     with pytest.raises(ValueError, match="requires parameter 'shot'"):
#         orchestrator.trigger_run(definition.name, parameters={"priority": "rush"})


# def test_trigger_run_rejects_unknown_parameter(
#     orchestrator: PipelineOrchestrator,
# ) -> None:
#     definition = _parameterised_pipeline()
#     orchestrator.register(definition)

#     with pytest.raises(ValueError, match="does not define parameters: extra"):
#         run = orchestrator.trigger_run(
#             definition.name,
#             parameters={"shot": "sh030", "extra": "value"},
#         )
#         print(run)
#         if metrics["count"] > 0 and metrics["total_duration_ms"] is not None:
#             assert metrics["average_duration_ms"] is not None


# def test_serialise_preserves_provider_identifier(
#     monkeypatch: pytest.MonkeyPatch,
# ) -> None:
#     class CallableProvider:
#         def __call__(self, parameters: dict[str, object]) -> None:
#             _ = parameters

#     def callable_factory(config: dict[str, object]) -> CallableProvider:
#         _ = config
#         return CallableProvider()

#     monkeypatch.setattr(
#         pipeline_executor.plugins,
#         "discover_pipeline_step_factories",
#         lambda: {"callable-step": callable_factory},
#     )

#     orchestrator = PipelineOrchestrator()
#     pipeline = Pipeline(
#         name="serialisation",
#         steps=[PipelineStep(name="callable", provider="callable-step")],
#     )
#     definition = PipelineDefinition(
#         name="serialisation", pipeline=pipeline, parameters={}
#     )
#     orchestrator.register(definition)

#     stored = orchestrator.get_pipeline("serialisation")
#     snapshot = stored.serialise()

#     assert snapshot["steps"][0]["provider"] == "callable-step"
#     assert snapshot["providers"]["callable"] == "callable-step"


# def test_orchestrator_marks_failure(monkeypatch: pytest.MonkeyPatch) -> None:
#     def failing_factory(
#         config: dict[str, object]
#     ) -> Callable[[dict[str, object]], None]:
#         def provider(parameters: dict[str, object]) -> None:
#             raise RuntimeError("boom")

#         return provider

#     monkeypatch.setattr(
#         pipeline_executor.plugins,
#         "discover_pipeline_step_factories",
#         lambda: {"fails": failing_factory},
#     )

#     orchestrator = PipelineOrchestrator()
#     pipeline = Pipeline(
#         name="failure",
#         steps=[PipelineStep(name="explode", provider="fails")],
#     )
#     definition = PipelineDefinition(name="failure", pipeline=pipeline, parameters={})
#     orchestrator.register(definition)

#     run = orchestrator.trigger_run("failure")
#     assert run.status in {"queued", "running"}

#     run = _wait_for_run(orchestrator, run.run_id, status="failed")

#     events = list(orchestrator.iter_run_events(run.run_id))
#     statuses = [event.status for event in events]
#     assert statuses[-2:] == ["step_failed", "failed"]
#     assert "error" in events[-2].parameters


# def test_upsert_registers_new_pipeline(orchestrator: PipelineOrchestrator) -> None:
#     pipeline = _build_pipeline()
#     definition = PipelineDefinition(
#         name="demo",
#         pipeline=pipeline,
#         display_name="Demo pipeline",
#         parameters={},
#     )

#     created = orchestrator.upsert(definition)

#     assert created is True
#     stored = orchestrator.get_pipeline("demo")
#     assert stored.display_name == "Demo pipeline"


# def test_upsert_replaces_existing_pipeline(orchestrator: PipelineOrchestrator) -> None:
#     initial = PipelineDefinition(name="demo", pipeline=_build_pipeline(), parameters={})
#     orchestrator.register(initial)

#     replacement = PipelineDefinition(
#         name="demo",
#         pipeline=Pipeline(
#             name="demo",
#             steps=[
#                 PipelineStep(name="seed", provider="tests.pipeline:prepare"),
#                 PipelineStep(
#                     name="publish",
#                     provider="tests.pipeline:publish",
#                     trigger=TriggerPolicy(depends_on=("seed",)),
#                 ),
#             ],
#             metadata={"revision": 2},
#         ),
#         description="Updated",
#         parameters={"priority": ParameterDefinition(default="high")},
#     )

#     created = orchestrator.upsert(replacement)

#     assert created is False
#     stored = orchestrator.get_pipeline("demo")
#     assert stored.description == "Updated"
#     assert stored.pipeline.metadata["revision"] == 2
#     assert [step.name for step in stored.pipeline.steps] == ["seed", "publish"]
#     assert stored.parameters["priority"].default == "high"


# def test_deregister_removes_pipeline(orchestrator: PipelineOrchestrator) -> None:
#     pipeline = _build_pipeline()
#     definition = PipelineDefinition(
#         name="demo",
#         pipeline=pipeline,
#         parameters={
#             "department": ParameterDefinition(default="lighting"),
#             "shot": ParameterDefinition(default="sh010"),
#         },
#     )
#     orchestrator.register(definition)

#     orchestrator.deregister("demo")

#     with pytest.raises(KeyError):
#         orchestrator.get_pipeline("demo")


# def test_deregister_unknown_pipeline_raises(orchestrator: PipelineOrchestrator) -> None:
#     with pytest.raises(KeyError):
#         orchestrator.deregister("missing")


# def test_trigger_run_returns_before_completion(monkeypatch: pytest.MonkeyPatch) -> None:
#     release = threading.Event()

#     def blocking_factory(
#         config: dict[str, object]
#     ) -> Callable[[dict[str, object]], None]:
#         def provider(parameters: dict[str, object]) -> None:
#             release.wait(timeout=1)

#         return provider

#     monkeypatch.setattr(
#         pipeline_executor.plugins,
#         "discover_pipeline_step_factories",
#         lambda: {"blocking": blocking_factory},
#     )

#     orchestrator = PipelineOrchestrator()
#     pipeline = Pipeline(
#         name="delayed",
#         steps=[PipelineStep(name="wait", provider="blocking")],
#     )
#     definition = PipelineDefinition(name="delayed", pipeline=pipeline, parameters={})
#     orchestrator.register(definition)

#     run = orchestrator.trigger_run("delayed")

#     assert run.status in {"queued", "running"}

#     events = list(orchestrator.iter_run_events(run.run_id))
#     statuses = [event.status for event in events]
#     assert statuses[0] == "queued"
#     assert "succeeded" not in statuses
#     assert "failed" not in statuses

#     release.set()
#     run = _wait_for_run(orchestrator, run.run_id, status="succeeded")

#     statuses = [event.status for event in orchestrator.iter_run_events(run.run_id)]
#     assert statuses[-2:] == ["step_succeeded", "succeeded"]


# def test_trigger_run_records_failure_after_return(
#     monkeypatch: pytest.MonkeyPatch,
# ) -> None:
#     release = threading.Event()

#     def blocking_factory(config: dict[str, object]) -> None:
#         def provider(parameters: dict[str, object]) -> None:
#             release.wait(timeout=1)
#             raise RuntimeError("boom")


# def test_orchestrator_supports_async_providers(
#     monkeypatch: pytest.MonkeyPatch, tmp_path: Path
# ) -> None:
#     import asyncio

#     captured: list[tuple[str, dict[str, object]]] = []

#     def sequential_factory(
#         config: dict[str, object]
#     ) -> Callable[[dict[str, object]], object]:
#         async def provider(parameters: dict[str, object]) -> Mapping[str, object]:
#             payload = {
#                 "department": parameters.get("department", "effects"),
#                 "shot": parameters.get("shot", "sh030"),
#             }

#             async def emit_events() -> AsyncIterator[tuple[str, Mapping[str, object]]]:
#                 yield ("asset.ingested", payload)

#             return {"events": emit_events()}

#         return provider

#     def event_factory(
#         config: dict[str, object]
#     ) -> Callable[[pipeline_executor.StepTriggerEvent, dict[str, object]], object]:
#         async def provider(
#             event: pipeline_executor.StepTriggerEvent,
#             parameters: dict[str, object],
#         ) -> None:
#             await asyncio.sleep(0)
#             captured.append((event.name, dict(event.payload)))

#         return provider

#     monkeypatch.setattr(
#         pipeline_executor.plugins,
#         "discover_pipeline_step_factories",
#         lambda: {"sequential": sequential_factory, "event-listener": event_factory},
#     )

#     store = PipelineRunStore(database=tmp_path / "async.sqlite3")
#     orchestrator = PipelineOrchestrator(store=store)
#     pipeline = _build_pipeline()
#     definition = PipelineDefinition(
#         name="demo",
#         pipeline=pipeline,
#         parameters={
#             "department": ParameterDefinition(default="lighting"),
#             "shot": ParameterDefinition(default="sh010"),
#         },
#     )
#     orchestrator.register(definition)

#     run = orchestrator.trigger_run(
#         "demo", parameters={"department": "lighting", "shot": "sh040"}
#     )

#     assert run.status == "running"
#     events = list(orchestrator.iter_run_events(run.run_id))
#     statuses = [event.status for event in events]
#     if statuses != ["queued", "running", "step_started"]:
#         deadline = time.monotonic() + 1.0
#         while time.monotonic() < deadline:
#             events = list(orchestrator.iter_run_events(run.run_id))
#             statuses = [event.status for event in events]
#             if len(statuses) >= 3:
#                 break
#             time.sleep(0.01)

#     assert statuses[:3] == [
#         "queued",
#         "running",
#         "step_started",
#     ]


# def test_shutdown_closes_store(tmp_path: Path) -> None:
#     database_path = tmp_path / "runs.sqlite3"
#     store = PipelineRunStore(database=database_path)
#     orchestrator = PipelineOrchestrator(store=store)

#     orchestrator.shutdown()
#     orchestrator.shutdown()

#     assert store._closed is True
#     assert store._subscribers == {}

#     reopened = PipelineOrchestrator(store=PipelineRunStore(database=database_path))
#     try:
#         assert reopened.list_runs() == []
#     finally:
#         reopened.shutdown()
