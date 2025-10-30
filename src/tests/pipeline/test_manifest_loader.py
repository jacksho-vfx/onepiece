"""Regression tests for pipeline manifest translation."""

from __future__ import annotations

from pathlib import Path

import pytest
from typing import Any

from apps.trafalgar.app import _extract_pipeline_definition
from apps.trafalgar.pipeline import PipelineOrchestrator


yaml = pytest.importorskip("yaml")


@pytest.mark.parametrize(
    "manifest_path",
    (
        Path("docs/examples/pipelines/linear/pipeline.yaml"),
        Path("docs/examples/pipelines/event-driven/pipeline.yaml"),
    ),
)
def test_sample_manifests_can_be_upserted(manifest_path: Path) -> None:
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)

    definition = _extract_pipeline_definition(payload)

    orchestrator = PipelineOrchestrator(executor=_PassthroughExecutor())
    orchestrator.upsert(definition)

    registered = orchestrator.get_pipeline(definition.name)
    assert registered.name == definition.name
    steps = list(registered.pipeline.steps)
    assert steps

    for step in steps:
        assert isinstance(step.provider, str)
        assert isinstance(step.config, dict)
        if manifest_path.parts[-2] == "event-driven":
            assert step.trigger.is_event_driven
        else:
            assert step.trigger.is_sequential


class _PassthroughExecutor:
    def resolve_pipeline(self, pipeline: Any) -> Any:
        return pipeline
