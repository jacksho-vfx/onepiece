"""Integration tests ensuring pipeline runs persist across orchestrator restarts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time

import textwrap
import pytest

from apps.onepiece.config import load_profile
from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineOrchestrator,
    PipelineRun,
    PipelineRunStore,
    configure_orchestrator_from_profile,
    get_pipeline_orchestrator,
    set_pipeline_orchestrator,
)
from apps.trafalgar.providers import pipeline_executor
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy


def _wait_for_completion(
    orchestrator: PipelineOrchestrator,
    run_id: str,
    *,
    timeout: float = 5.0,
) -> PipelineRun:
    deadline = time.monotonic() + timeout
    while True:
        run = orchestrator.get_run(run_id)
        if run.status in {"succeeded", "failed"}:
            return run
        if time.monotonic() >= deadline:
            msg = f"timed out waiting for run '{run_id}' to complete"
            raise AssertionError(msg)
        time.sleep(0.01)


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
    run = _wait_for_completion(orchestrator, run.run_id)
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


def test_run_definition_snapshot_survives_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_test_factories(monkeypatch)
    store = PipelineRunStore()
    orchestrator = PipelineOrchestrator(store=store)

    initial_pipeline = _build_pipeline()
    orchestrator.register(
        PipelineDefinition(name="demo", pipeline=initial_pipeline, parameters={})
    )

    run = orchestrator.trigger_run("demo")
    serialised = orchestrator.serialise_run(run.run_id)
    snapshot = serialised["definition_snapshot"]
    assert [step["name"] for step in snapshot["steps"]] == [
        "seed",
        "listener",
    ]

    mutated_pipeline = Pipeline(
        name="demo",
        steps=[
            PipelineStep(name="seed", provider="sequential"),
            PipelineStep(
                name="validate",
                provider="event-listener",
                trigger=TriggerPolicy(depends_on=("seed",)),
            ),
            PipelineStep(
                name="publish",
                provider="event-listener",
                trigger=TriggerPolicy(depends_on=("validate",)),
            ),
        ],
        metadata={"revision": 2},
    )
    orchestrator.upsert(
        PipelineDefinition(name="demo", pipeline=mutated_pipeline, parameters={})
    )

    mutated_definition = orchestrator.get_pipeline("demo")
    assert [step.name for step in mutated_definition.pipeline.steps] == [
        "seed",
        "validate",
        "publish",
    ]

    persisted_snapshot = orchestrator.serialise_run(run.run_id)["definition_snapshot"]
    assert [step["name"] for step in persisted_snapshot["steps"]] == [
        "seed",
        "listener",
    ]


def test_configure_orchestrator_from_profile_uses_profile_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_pipeline_orchestrator(None)

    project_root = tmp_path / "project"
    project_root.mkdir()
    database = tmp_path / "runs.sqlite3"
    config_path = project_root / "onepiece.toml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            default_profile = "default"

            [profiles.default.pipeline.storage]
            database = "{database}"

            [pipelines.render_shots]
            display_name = "Render Shots"
            description = "Render queued shots with default settings."

            [[pipelines.render_shots.steps]]
            name = "prepare"
            provider = "tests.pipeline:prepare"

            [[pipelines.render_shots.steps]]
            name = "render"
            provider = "tests.pipeline:render"

            [[pipelines.render_shots.steps]]
            name = "notify"
            provider = "tests.pipeline:notify"

            [pipelines.render_shots.steps.trigger]
            kind = "event"
            event = "render.completed"
            depends_on = ["render"]

            [pipelines.render_shots.parameters]
            quality = "string"
            priority = "int"
            """
        ).strip()
        + "\n"
    )

    monkeypatch.delenv("ONEPIECE_PROFILE", raising=False)

    context = load_profile(project_root=project_root)
    assert context.pipeline_storage == {"database": str(database)}

    orchestrator = configure_orchestrator_from_profile(
        context, storage_config=context.pipeline_storage
    )
    run = orchestrator.trigger_run("render_shots", parameters={"quality": "high"})
    run = _wait_for_completion(orchestrator, run.run_id)
    statuses = [event.status for event in orchestrator.iter_run_events(run.run_id)]

    set_pipeline_orchestrator(None)

    restarted_context = load_profile(project_root=project_root)
    restarted = configure_orchestrator_from_profile(
        restarted_context, storage_config=restarted_context.pipeline_storage
    )

    persisted_run = restarted.get_run(run.run_id)
    assert persisted_run.status == run.status
    assert persisted_run.pipeline == "render_shots"
    assert [event.status for event in restarted.iter_run_events(run.run_id)] == statuses

    set_pipeline_orchestrator(None)


def test_get_pipeline_orchestrator_accepts_storage_config(
    tmp_path: Path,
) -> None:
    set_pipeline_orchestrator(None)
    db_path = tmp_path / "shared.sqlite3"
    orchestrator = get_pipeline_orchestrator(storage_config={"database": str(db_path)})
    try:
        assert orchestrator is get_pipeline_orchestrator()
        with pytest.raises(RuntimeError):
            get_pipeline_orchestrator(storage_config={"database": str(db_path)})
    finally:
        set_pipeline_orchestrator(None)
