"""Regression tests for pipeline manifest translation."""

from __future__ import annotations

from pathlib import Path

import pytest
from typing import Any

from apps.onepiece.pipeline import _serialised_definition_to_manifest
from apps.trafalgar.app import _extract_pipeline_definition
from apps.trafalgar.pipeline import (
    PipelineOrchestrator,
    pipeline_definition_from_profile_entry,
)
from apps.trafalgar.pipeline_manifest import translate_pipeline_manifest


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


def test_manifest_version_round_trip() -> None:
    manifest = {
        "name": "demo",
        "version": "2024.1",
        "steps": [
            {
                "id": "first",
                "uses": "tests.pipeline:prepare",
            }
        ],
    }

    translated = translate_pipeline_manifest(manifest)
    assert translated["metadata"]["version"] == "2024.1"

    definition = pipeline_definition_from_profile_entry("demo", translated)
    assert definition.version == "2024.1"
    assert definition.pipeline.metadata["version"] == "2024.1"

    serialised = definition.serialise()
    assert serialised["version"] == "2024.1"
    assert serialised["metadata"]["version"] == "2024.1"

    exported = _serialised_definition_to_manifest(serialised)
    assert exported["version"] == "2024.1"
    assert "version" not in (exported.get("metadata") or {})

    retranslated = translate_pipeline_manifest(exported)
    assert retranslated["metadata"]["version"] == "2024.1"
