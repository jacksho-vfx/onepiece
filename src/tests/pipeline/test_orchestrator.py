"""Behavioural tests for the Trafalgar pipeline orchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
import threading
import time
from typing import Mapping

import pytest

from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineOrchestrator,
    PipelineRun,
    PipelineRunStore,
)
from apps.trafalgar.providers import pipeline_executor
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy


@pytest.fixture
def orchestrator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> PipelineOrchestrator:
    """Return an orchestrator configured with deterministic step factories."""

    def sequential_factory(
        config: dict[str, object]
    ) -> Callable[[dict[str, object]], list[tuple[str, dict[str, object]]]]:
        def provider(
            parameters: dict[str, object]
        ) -> list[tuple[str, dict[str, object]]]:
            event_payload = {
                "department": parameters.get("department", "lighting"),
                "shot": parameters.get("shot", "sh010"),
            }
            return [("asset.ingested", event_payload)]

        return provider

    def event_factory(
        config: dict[str, object]
    ) -> Callable[[pipeline_executor.StepTriggerEvent, dict[str, object]], None]:
        def provider(
            event: pipeline_executor.StepTriggerEvent, parameters: dict[str, object]
        ) -> None:
            _ = (
                config,
                event,
                parameters,
            )  # pragma: no cover - exercise callable signature

        return provider

    monkeypatch.setattr(
        pipeline_executor.plugins,
        "discover_pipeline_step_factories",
        lambda: {"sequential": sequential_factory, "event-listener": event_factory},
    )

    store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
    return PipelineOrchestrator(store=store)


def _wait_for_run(
    orchestrator: PipelineOrchestrator,
    run_id: str,
    *,
    status: str,
    timeout: float = 5.0,
) -> PipelineRun:
    deadline = time.monotonic() + timeout
    while True:
        run = orchestrator.get_run(run_id)
        if run.status == status:
            return run
        if time.monotonic() >= deadline:
            msg = f"timed out waiting for run '{run_id}' to reach status '{status}'"
            raise AssertionError(msg)
        time.sleep(0.01)


def _build_pipeline() -> Pipeline:
    return Pipeline(
        name="demo",
        steps=[
            PipelineStep(
                name="seed",
                provider="sequential",
                config={"emits": "asset.ingested"},
            ),
            PipelineStep(
                name="listener",
                provider="event-listener",
                config={"expects": "asset.ingested"},
                trigger=TriggerPolicy(
                    kind="event",
                    event="asset.ingested",
                    filters={"department": "lighting"},
                    depends_on=("seed",),
                ),
            ),
        ],
    )


def test_orchestrator_emits_step_events(orchestrator: PipelineOrchestrator) -> None:
    pipeline = _build_pipeline()
    definition = PipelineDefinition(name="demo", pipeline=pipeline, parameters={})
    orchestrator.register(definition)

    run = orchestrator.trigger_run(
        "demo", parameters={"department": "lighting", "shot": "sh020"}
    )
    assert run.status in {"queued", "running"}

    run = _wait_for_run(orchestrator, run.run_id, status="succeeded")

    events = list(orchestrator.iter_run_events(run.run_id))
    statuses = [event.status for event in events]
    assert statuses == [
        "queued",
        "running",
        "step_started",
        "step_succeeded",
        "step_started",
        "step_succeeded",
        "succeeded",
    ]

    step_payloads = [
        event.parameters for event in events if event.status.startswith("step_")
    ]
    assert step_payloads[0]["step"] == "seed"
    assert step_payloads[1]["step"] == "seed"
    assert step_payloads[2]["step"] == "listener"
    assert step_payloads[2]["event"]["name"] == "asset.ingested"
    assert step_payloads[2]["event"]["payload"]["shot"] == "sh020"


def test_serialise_preserves_provider_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CallableProvider:
        def __call__(self, parameters: dict[str, object]) -> None:
            _ = parameters

    def callable_factory(config: dict[str, object]) -> CallableProvider:
        _ = config
        return CallableProvider()

    monkeypatch.setattr(
        pipeline_executor.plugins,
        "discover_pipeline_step_factories",
        lambda: {"callable-step": callable_factory},
    )

    orchestrator = PipelineOrchestrator()
    pipeline = Pipeline(
        name="serialisation",
        steps=[PipelineStep(name="callable", provider="callable-step")],
    )
    definition = PipelineDefinition(
        name="serialisation", pipeline=pipeline, parameters={}
    )
    orchestrator.register(definition)

    stored = orchestrator.get_pipeline("serialisation")
    snapshot = stored.serialise()

    assert snapshot["steps"][0]["provider"] == "callable-step"
    assert snapshot["providers"]["callable"] == "callable-step"


def test_orchestrator_marks_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_factory(
        config: dict[str, object]
    ) -> Callable[[dict[str, object]], None]:
        def provider(parameters: dict[str, object]) -> None:
            raise RuntimeError("boom")

        return provider

    monkeypatch.setattr(
        pipeline_executor.plugins,
        "discover_pipeline_step_factories",
        lambda: {"fails": failing_factory},
    )

    orchestrator = PipelineOrchestrator()
    pipeline = Pipeline(
        name="failure",
        steps=[PipelineStep(name="explode", provider="fails")],
    )
    definition = PipelineDefinition(name="failure", pipeline=pipeline, parameters={})
    orchestrator.register(definition)

    run = orchestrator.trigger_run("failure")
    assert run.status in {"queued", "running"}

    run = _wait_for_run(orchestrator, run.run_id, status="failed")

    events = list(orchestrator.iter_run_events(run.run_id))
    statuses = [event.status for event in events]
    assert statuses[-2:] == ["step_failed", "failed"]
    assert "error" in events[-2].parameters


def test_upsert_registers_new_pipeline(orchestrator: PipelineOrchestrator) -> None:
    pipeline = _build_pipeline()
    definition = PipelineDefinition(
        name="demo",
        pipeline=pipeline,
        display_name="Demo pipeline",
        parameters={},
    )

    created = orchestrator.upsert(definition)

    assert created is True
    stored = orchestrator.get_pipeline("demo")
    assert stored.display_name == "Demo pipeline"


def test_upsert_replaces_existing_pipeline(orchestrator: PipelineOrchestrator) -> None:
    initial = PipelineDefinition(name="demo", pipeline=_build_pipeline(), parameters={})
    orchestrator.register(initial)

    replacement = PipelineDefinition(
        name="demo",
        pipeline=Pipeline(
            name="demo",
            steps=[
                PipelineStep(name="seed", provider="tests.pipeline:prepare"),
                PipelineStep(
                    name="publish",
                    provider="tests.pipeline:publish",
                    trigger=TriggerPolicy(depends_on=("seed",)),
                ),
            ],
            metadata={"revision": 2},
        ),
        description="Updated",
        parameters={"priority": "high"},
    )

    created = orchestrator.upsert(replacement)

    assert created is False
    stored = orchestrator.get_pipeline("demo")
    assert stored.description == "Updated"
    assert stored.pipeline.metadata["revision"] == 2
    assert [step.name for step in stored.pipeline.steps] == ["seed", "publish"]
    assert stored.parameters == {"priority": "high"}


def test_deregister_removes_pipeline(orchestrator: PipelineOrchestrator) -> None:
    pipeline = _build_pipeline()
    definition = PipelineDefinition(name="demo", pipeline=pipeline, parameters={})
    orchestrator.register(definition)

    orchestrator.deregister("demo")

    with pytest.raises(KeyError):
        orchestrator.get_pipeline("demo")


def test_deregister_unknown_pipeline_raises(orchestrator: PipelineOrchestrator) -> None:
    with pytest.raises(KeyError):
        orchestrator.deregister("missing")


def test_trigger_run_returns_before_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def blocking_factory(
        config: dict[str, object]
    ) -> Callable[[dict[str, object]], None]:
        def provider(parameters: dict[str, object]) -> None:
            release.wait(timeout=1)

        return provider

    monkeypatch.setattr(
        pipeline_executor.plugins,
        "discover_pipeline_step_factories",
        lambda: {"blocking": blocking_factory},
    )

    orchestrator = PipelineOrchestrator()
    pipeline = Pipeline(
        name="delayed",
        steps=[PipelineStep(name="wait", provider="blocking")],
    )
    definition = PipelineDefinition(name="delayed", pipeline=pipeline, parameters={})
    orchestrator.register(definition)

    run = orchestrator.trigger_run("delayed")

    assert run.status in {"queued", "running"}

    events = list(orchestrator.iter_run_events(run.run_id))
    statuses = [event.status for event in events]
    assert statuses[0] == "queued"
    assert "succeeded" not in statuses
    assert "failed" not in statuses

    release.set()
    run = _wait_for_run(orchestrator, run.run_id, status="succeeded")

    statuses = [event.status for event in orchestrator.iter_run_events(run.run_id)]
    assert statuses[-2:] == ["step_succeeded", "succeeded"]


def test_trigger_run_records_failure_after_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()

    def blocking_factory(config: dict[str, object]) -> None:
        def provider(parameters: dict[str, object]) -> None:
            release.wait(timeout=1)
            raise RuntimeError("boom")


def test_orchestrator_supports_async_providers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    captured: list[tuple[str, dict[str, object]]] = []

    def sequential_factory(
        config: dict[str, object]
    ) -> Callable[[dict[str, object]], object]:
        async def provider(parameters: dict[str, object]) -> Mapping[str, object]:
            payload = {
                "department": parameters.get("department", "effects"),
                "shot": parameters.get("shot", "sh030"),
            }

            async def emit_events() -> AsyncIterator[tuple[str, Mapping[str, object]]]:
                yield ("asset.ingested", payload)

            return {"events": emit_events()}

        return provider

    def event_factory(
        config: dict[str, object]
    ) -> Callable[[pipeline_executor.StepTriggerEvent, dict[str, object]], object]:
        async def provider(
            event: pipeline_executor.StepTriggerEvent,
            parameters: dict[str, object],
        ) -> None:
            await asyncio.sleep(0)
            captured.append((event.name, dict(event.payload)))

        return provider

    monkeypatch.setattr(
        pipeline_executor.plugins,
        "discover_pipeline_step_factories",
        lambda: {"sequential": sequential_factory, "event-listener": event_factory},
    )

    store = PipelineRunStore(database=tmp_path / "async.sqlite3")
    orchestrator = PipelineOrchestrator(store=store)
    pipeline = _build_pipeline()
    definition = PipelineDefinition(name="demo", pipeline=pipeline, parameters={})
    orchestrator.register(definition)

    run = orchestrator.trigger_run(
        "demo", parameters={"department": "lighting", "shot": "sh040"}
    )

    assert run.status == "running"
    events = list(orchestrator.iter_run_events(run.run_id))
    statuses = [event.status for event in events]
    if statuses != ["queued", "running", "step_started"]:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            events = list(orchestrator.iter_run_events(run.run_id))
            statuses = [event.status for event in events]
            if len(statuses) >= 3:
                break
            time.sleep(0.01)

    assert statuses[:3] == [
        "queued",
        "running",
        "step_started",
    ]


def test_shutdown_closes_store(tmp_path: Path) -> None:
    database_path = tmp_path / "runs.sqlite3"
    store = PipelineRunStore(database=database_path)
    orchestrator = PipelineOrchestrator(store=store)

    orchestrator.shutdown()
    orchestrator.shutdown()

    assert store._closed is True
    assert store._subscribers == {}

    reopened = PipelineOrchestrator(store=PipelineRunStore(database=database_path))
    try:
        assert reopened.list_runs() == []
    finally:
        reopened.shutdown()
