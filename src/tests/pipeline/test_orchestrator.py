"""Behavioural tests for the Trafalgar pipeline orchestrator."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.trafalgar.pipeline import PipelineDefinition, PipelineOrchestrator
from apps.trafalgar.providers import pipeline_executor
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy


@pytest.fixture
def orchestrator(monkeypatch: pytest.MonkeyPatch) -> PipelineOrchestrator:
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

    return PipelineOrchestrator()


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
    assert run.status == "succeeded"

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
    assert run.status == "failed"

    events = list(orchestrator.iter_run_events(run.run_id))
    statuses = [event.status for event in events]
    assert statuses[-2:] == ["step_failed", "failed"]
    assert "error" in events[-2].parameters
