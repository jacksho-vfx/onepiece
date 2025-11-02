"""Helpers for staging pipeline demo assets used by the tester CLI."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from dataclasses import replace

import yaml

from apps.trafalgar.pipeline import (
    get_pipeline_orchestrator,
    pipeline_definition_from_profile_entry,
    PipelineDefinition,
)
from apps.trafalgar.pipeline_manifest import translate_pipeline_manifest
from apps.trafalgar.providers.pipeline_executor import (
    PROVIDER_REFERENCE_METADATA_KEY,
)
from libraries.pipeline.models import Pipeline, PipelineStep

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PIPELINE_EXAMPLES = _REPO_ROOT / "docs" / "examples" / "pipelines"
_PIPELINE_FIXTURES = _REPO_ROOT / ".fixtures" / "pipelines"

_PIPELINE_ENVIRONMENT_OVERRIDES: dict[str, tuple[bool, str]] = {}
_STAGED_PIPELINE_PROJECT_ROOT: Path | None = None


def prepare_pipeline_demos() -> None:
    """Stage pipeline example projects and register them with the orchestrator."""

    global _PIPELINE_ENVIRONMENT_OVERRIDES
    global _STAGED_PIPELINE_PROJECT_ROOT

    staged_root = _stage_examples()
    orchestrator = get_pipeline_orchestrator()

    first_project_root: Path | None = None
    for project_root in sorted(path for path in staged_root.iterdir() if path.is_dir()):
        manifest_path = project_root / "pipeline.yaml"
        if not manifest_path.exists():
            continue
        manifest = _load_manifest(manifest_path)
        translated = translate_pipeline_manifest(manifest)
        name = translated.get("name")
        if not isinstance(name, str) or not name:
            msg = f"pipeline manifest '{manifest_path}' must define a non-empty name"
            raise ValueError(msg)
        definition = pipeline_definition_from_profile_entry(name, translated)
        definition = _definition_with_stubbed_providers(definition)
        orchestrator.upsert(definition)
        if first_project_root is None:
            first_project_root = project_root

    if first_project_root is None:
        first_project_root = staged_root

    overrides = {
        "ONEPIECE_PROJECT_ROOT": str(first_project_root),
    }
    _PIPELINE_ENVIRONMENT_OVERRIDES = _apply_environment_overrides(overrides)
    _STAGED_PIPELINE_PROJECT_ROOT = first_project_root


def restore_pipeline_demo_environment() -> None:
    """Restore environment variables overridden while staging demo pipelines."""

    global _PIPELINE_ENVIRONMENT_OVERRIDES
    global _STAGED_PIPELINE_PROJECT_ROOT

    overrides = _PIPELINE_ENVIRONMENT_OVERRIDES
    _PIPELINE_ENVIRONMENT_OVERRIDES = {}

    for key, (existed, previous_value) in overrides.items():
        if existed:
            os.environ[key] = previous_value
        else:
            os.environ.pop(key, None)

    _STAGED_PIPELINE_PROJECT_ROOT = None


def get_staged_pipeline_project_root() -> Path | None:
    """Return the staged pipeline project root, if one has been prepared."""

    return _STAGED_PIPELINE_PROJECT_ROOT


def _stage_examples() -> Path:
    if not _PIPELINE_EXAMPLES.exists():
        msg = f"pipeline examples directory '{_PIPELINE_EXAMPLES}' is missing"
        raise FileNotFoundError(msg)

    if _PIPELINE_FIXTURES.exists():
        shutil.rmtree(_PIPELINE_FIXTURES)
    _PIPELINE_FIXTURES.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_PIPELINE_EXAMPLES, _PIPELINE_FIXTURES)
    return _PIPELINE_FIXTURES


def _load_manifest(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        msg = f"pipeline manifest '{path}' must deserialize to a mapping"
        raise TypeError(msg)
    return dict(payload)


def _apply_environment_overrides(
    updates: Mapping[str, str],
) -> dict[str, tuple[bool, str]]:
    previous: dict[str, tuple[bool, str]] = {}
    for key, value in updates.items():
        existed = key in os.environ
        if existed:
            previous[key] = (True, os.environ[key])
        else:
            previous[key] = (False, "")
        os.environ[key] = value
    return previous


def _definition_with_stubbed_providers(
    definition: PipelineDefinition,
) -> PipelineDefinition:
    pipeline = definition.pipeline
    updated_steps: list[PipelineStep] = []
    mutated = False
    for step in pipeline.steps:
        provider = step.provider
        if isinstance(provider, str):
            mutated = True
            metadata = dict(step.metadata)
            metadata.setdefault(PROVIDER_REFERENCE_METADATA_KEY, provider)
            stub = _make_stub_provider(provider)
            updated_steps.append(replace(step, provider=stub, metadata=metadata))
        else:
            updated_steps.append(step)

    if not mutated:
        return definition

    updated_pipeline = Pipeline(
        name=pipeline.name,
        steps=updated_steps,
        metadata=pipeline.metadata,
    )
    return replace(definition, pipeline=updated_pipeline)


def _make_stub_provider(reference: str) -> Callable[..., None]:
    def _stub_provider(*_args: Any, **_kwargs: Any) -> None:
        return None

    _stub_provider.__name__ = (
        f"stub_provider_for_{reference.replace('.', '_').replace(':', '_')}"
    )
    return _stub_provider


__all__ = [
    "prepare_pipeline_demos",
    "restore_pipeline_demo_environment",
    "get_staged_pipeline_project_root",
]
