"""Integration tests ensuring pipeline runs persist across orchestrator restarts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineOrchestrator,
    PipelineRunStore,
    get_pipeline_orchestrator,
    set_pipeline_orchestrator,
)
from apps.trafalgar.providers import pipeline_executor
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy


def _register_test_factories(monkeypatch: pytest.MonkeyPatch) -> None:
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
            _ = (config, event, parameters)

        return provider

    monkeypatch.setattr(
        pipeline_executor.plugins,
        "discover_pipeline_step_factories",
        lambda: {"sequential": sequential_factory, "event-listener": event_factory},
    )


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


def test_pipeline_history_survives_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _register_test_factories(monkeypatch)
    store_path = tmp_path / "persistent.sqlite3"
    store = PipelineRunStore(database=store_path)
    orchestrator = PipelineOrchestrator(store=store)

    pipeline = _build_pipeline()
    orchestrator.register(
        PipelineDefinition(name="demo", pipeline=pipeline, parameters={})
    )

    run = orchestrator.trigger_run(
        "demo", parameters={"department": "lighting", "shot": "sh020"}
    )
    statuses = [event.status for event in orchestrator.iter_run_events(run.run_id)]

    new_store = PipelineRunStore(database=store_path)
    restarted = PipelineOrchestrator(store=new_store)

    persisted_run = restarted.get_run(run.run_id)
    assert persisted_run.status == run.status
    assert persisted_run.pipeline == "demo"

    persisted_events = list(restarted.iter_run_events(run.run_id))
    assert [event.status for event in persisted_events] == statuses

    stream_payload = restarted.serialise_run_events(run.run_id)
    assert [payload["status"] for payload in stream_payload] == statuses


def test_get_pipeline_orchestrator_accepts_storage_config(
    tmp_path: Path,
) -> None:
    set_pipeline_orchestrator(None)
    db_path = tmp_path / "shared.sqlite3"
    orchestrator = get_pipeline_orchestrator(
        storage_config={"database": str(db_path)}
    )
    try:
        assert orchestrator is get_pipeline_orchestrator()
        with pytest.raises(RuntimeError):
            get_pipeline_orchestrator(storage_config={"database": str(db_path)})
    finally:
        set_pipeline_orchestrator(None)

