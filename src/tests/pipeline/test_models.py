"""Tests for pipeline dataclasses and helpers."""

from __future__ import annotations

import sys

import pytest

from apps.trafalgar.pipeline import PipelineDefinition

from libraries.pipeline import (
    Pipeline,
    pipeline_from_config,
    pipelines_from_config,
    resolve_provider,
    with_resolved_providers,
)
from libraries.pipeline.models import PipelineStep, TriggerPolicy


def test_pipeline_from_config_sequential_defaults() -> None:
    config = {
        "name": "daily_publish",
        "steps": [
            {
                "name": "ingest",
                "provider": "src.tests.pipeline.dummies:uppercase_provider",
            },
            {
                "name": "validate",
                "provider": "src.tests.pipeline.dummies:uppercase_provider",
            },
            {
                "name": "publish",
                "provider": "src.tests.pipeline.dummies:uppercase_provider",
                "trigger": {"depends_on": ["validate"]},
            },
        ],
    }

    pipeline = pipeline_from_config(config)

    assert isinstance(pipeline, Pipeline)
    assert [step.name for step in pipeline.steps] == [
        "ingest",
        "validate",
        "publish",
    ]

    first, second, third = pipeline.steps
    assert first.trigger.is_sequential
    assert first.trigger.depends_on == ()
    assert second.trigger.depends_on == ("ingest",)
    assert third.trigger.depends_on == ("validate",)

    resolved = with_resolved_providers(pipeline)
    ingest_provider = resolved.get_step("ingest").provider
    assert callable(ingest_provider)
    assert ingest_provider("payload") == "PAYLOAD"


def test_trigger_policy_event_driven_configuration() -> None:
    trigger = TriggerPolicy.from_config(
        {
            "type": "event",
            "event": "asset.approved",
            "filters": {"department": "lighting"},
        }
    )

    assert trigger.is_event_driven
    assert trigger.event == "asset.approved"
    assert trigger.filters == {"department": "lighting"}


def test_pipeline_supports_event_driven_steps() -> None:
    config = {
        "name": "event_pipeline",
        "steps": [
            {
                "name": "listen",
                "provider": "src.tests.pipeline.dummies:Accumulator",
                "trigger": {
                    "kind": "event",
                    "event": "asset.ingested",
                    "filters": {"product": "comp"},
                },
            },
            {
                "name": "render",
                "provider": "src.tests.pipeline.dummies:uppercase_provider",
            },
        ],
    }

    pipeline = pipeline_from_config(config)
    listen_step, render_step = pipeline.steps

    assert listen_step.trigger.is_event_driven
    assert listen_step.trigger.event == "asset.ingested"
    assert listen_step.trigger.depends_on == ()
    assert render_step.trigger.depends_on == ("listen",)

    resolved = with_resolved_providers(pipeline)
    listen_provider = resolved.get_step("listen").provider
    assert callable(listen_provider)

    registry = {"cached": object()}
    assert resolve_provider("cached", registry=registry) is registry["cached"]
    assert resolve_provider("math.sqrt")(16) == 4


def test_pipelines_from_config_builds_multiple() -> None:
    configs = (
        {"name": "a", "steps": [{"name": "one", "provider": "math:sqrt"}]},
        {"name": "b", "steps": [{"name": "two", "provider": "math:floor"}]},
    )

    pipelines = pipelines_from_config(configs)
    assert len(pipelines) == 2
    assert {pipeline.name for pipeline in pipelines} == {"a", "b"}


def test_resolve_provider_supports_onepiece_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in list(sys.modules):
        if name == "onepiece" or name.startswith("onepiece."):
            monkeypatch.delitem(sys.modules, name, raising=False)
        if name == "apps.onepiece" or name.startswith("apps.onepiece."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    provider = resolve_provider("onepiece.aws.ingest:app")

    from apps.onepiece.aws import ingest as ingest_module

    assert provider is ingest_module.app
    assert sys.modules["onepiece"] is sys.modules["apps.onepiece"]
    assert sys.modules["onepiece.aws"] is sys.modules["apps.onepiece.aws"]
    assert sys.modules["onepiece.aws.ingest"] is sys.modules["apps.onepiece.aws.ingest"]


def test_pipeline_validation_errors() -> None:
    with pytest.raises(ValueError):
        Pipeline(name="broken", steps=[])

    with pytest.raises(ValueError):
        Pipeline(
            name="dupe",
            steps=[
                PipelineStep(name="same", provider="noop"),
                PipelineStep(name="same", provider="noop"),
            ],
        )

    with pytest.raises(ValueError):
        Pipeline(
            name="missing_dependency",
            steps=[
                PipelineStep(
                    name="primary",
                    provider="noop",
                    trigger=TriggerPolicy(depends_on=("other",)),
                )
            ],
        )

    trigger = TriggerPolicy(kind="event", event="asset.created")
    step = PipelineStep(name="listen", provider="noop", trigger=trigger)
    pipeline = Pipeline(name="ok", steps=[step])
    assert pipeline.get_step("listen") is step


def _build_single_step_pipeline() -> Pipeline:
    return pipeline_from_config(
        {
            "name": "demo",
            "steps": [
                {
                    "name": "single",
                    "provider": "math:sqrt",
                }
            ],
        }
    )


def test_pipeline_definition_resolve_parameters_coerces_and_defaults() -> None:
    pipeline = _build_single_step_pipeline()
    definition = PipelineDefinition(
        name="demo",
        pipeline=pipeline,
        parameters={
            "attempts": {"type": "integer", "default": "2"},
            "urgent": {"type": "boolean", "default": "false"},
            "mode": {
                "type": "string",
                "choices": ["auto", "manual"],
                "default": "auto",
            },
        },
    )

    resolved = definition.resolve_parameters({"attempts": "5", "urgent": "yes"})

    assert resolved == {"attempts": 5, "urgent": True, "mode": "auto"}


def test_pipeline_definition_resolve_parameters_rejects_invalid_values() -> None:
    pipeline = _build_single_step_pipeline()
    definition = PipelineDefinition(
        name="demo",
        pipeline=pipeline,
        parameters={
            "attempts": {"type": "integer"},
            "mode": {
                "type": "string",
                "choices": ["auto", "manual"],
            },
        },
    )

    with pytest.raises(ValueError, match="invalid literal"):
        definition.resolve_parameters({"attempts": "oops"})

    with pytest.raises(ValueError, match="must be one of"):
        definition.resolve_parameters({"attempts": 3, "mode": "invalid"})


def test_pipeline_definition_validates_default_choices() -> None:
    pipeline = _build_single_step_pipeline()

    with pytest.raises(ValueError, match="default must be one of"):
        PipelineDefinition(
            name="demo",
            pipeline=pipeline,
            parameters={
                "mode": {
                    "type": "string",
                    "choices": ["auto", "manual"],
                    "default": "invalid",
                }
            },
        )
