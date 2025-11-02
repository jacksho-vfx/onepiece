"""Helpers for staging pipeline demo assets used by the tester CLI."""

from __future__ import annotations

import json
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

    aggregated: dict[str, Mapping[str, Any]] = {}
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
        aggregated[name] = dict(translated)

    _write_aggregated_pipeline_configs(staged_root, aggregated)

    overrides = {
        "ONEPIECE_PROJECT_ROOT": str(staged_root),
    }
    _PIPELINE_ENVIRONMENT_OVERRIDES = _apply_environment_overrides(overrides)
    _STAGED_PIPELINE_PROJECT_ROOT = staged_root


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


def _write_aggregated_pipeline_configs(
    staged_root: Path, pipelines: Mapping[str, Mapping[str, Any]]
) -> None:
    config_path = staged_root / "onepiece.toml"
    if not pipelines:
        if config_path.exists():
            config_path.unlink()
        return

    staged_root.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# Auto-generated by prepare_pipeline_demos().",
        "# Consolidated pipeline definitions for the tester fixtures.",
        "",
    ]

    for name, config in sorted(pipelines.items()):
        lines.append(_format_toml_table_header("pipelines", name))
        for key, value in _iter_sorted_items(config):
            rendered = _render_toml_assignment(key, value)
            if rendered:
                lines.append(rendered)
        lines.append("")

    contents = "\n".join(lines).rstrip() + "\n"
    config_path.write_text(contents, encoding="utf-8")


def _iter_sorted_items(mapping: Mapping[str, Any]) -> list[tuple[str, Any]]:
    return sorted(mapping.items(), key=lambda item: str(item[0]))


def _render_toml_assignment(key: str, value: Any) -> str | None:
    if value is None:
        return None
    literal = _toml_literal(value)
    if literal is None:
        return None
    return f"{_format_toml_key(key)} = {literal}"


def _toml_literal(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, Mapping):
        return _toml_inline_table(value)
    if isinstance(value, (list, tuple)):
        return _toml_array(list(value))
    return json.dumps(value)


def _toml_array(values: list[Any]) -> str:
    if not values:
        return "[]"
    rendered = [
        _toml_literal(value) or "null"  # pragma: no cover - defensive guard
        for value in values
    ]
    return "[ " + ", ".join(rendered) + " ]"


def _toml_inline_table(mapping: Mapping[str, Any]) -> str:
    items = []
    for key, value in _iter_sorted_items(mapping):
        literal = _toml_literal(value)
        if literal is None:
            continue
        items.append(f"{_format_toml_key(key)} = {literal}")
    if not items:
        return "{}"
    return "{ " + ", ".join(items) + " }"


def _format_toml_table_header(*segments: str) -> str:
    formatted = ".".join(_format_toml_key(segment) for segment in segments)
    return f"[{formatted}]"


def _format_toml_key(key: str) -> str:
    text = str(key)
    if (
        text
        and text[0].isalpha()
        and all(char.isalnum() or char in {"-", "_"} for char in text)
    ):
        return text
    return json.dumps(text)


__all__ = [
    "prepare_pipeline_demos",
    "restore_pipeline_demo_environment",
    "get_staged_pipeline_project_root",
]
