"""Helpers for building pipeline registries from built-ins and studio config."""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, cast

import yaml  # type: ignore[import-untyped]

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from . import plugins
from .plugins import PipelineStepFactory
from .steps import builtin_pipeline_step_factories
from .templates import PipelineTemplate, list_pipeline_templates

StepFactory = Callable[[Mapping[str, Any]], Any]


class PipelineRegistryError(RuntimeError):
    """Raised when pipeline registries cannot be resolved."""


class PipelineTemplateLoadError(PipelineRegistryError):
    """Raised when a pipeline template cannot be loaded."""


def build_pipeline_step_factories(
    *,
    module_paths: Sequence[str] | None = None,
    builtin: Mapping[str, StepFactory] | None = None,
) -> dict[str, StepFactory]:
    """Return the merged pipeline step factory registry.

    ``module_paths`` points at Python modules that export either a
    ``pipeline_step_factories`` callable or a ``PIPELINE_STEP_FACTORIES``
    mapping.
    """

    builtin_factories = dict(builtin or builtin_pipeline_step_factories())
    registry = _discover_entry_point_factories(builtin_factories)

    if module_paths:
        module_factories = load_step_factories_from_modules(module_paths)
        registry = _merge_factories(registry, module_factories)

    return registry


def load_step_factories_from_modules(
    module_paths: Sequence[str],
) -> dict[str, StepFactory]:
    """Load step factories from a list of modules."""

    registry: dict[str, StepFactory] = {}
    for module_path in module_paths:
        name = str(module_path).strip()
        if not name:
            continue
        try:
            module = import_module(name)
        except ModuleNotFoundError as exc:
            raise PipelineRegistryError(
                f"Pipeline step factory module '{name}' could not be imported."
            ) from exc

        factories = _extract_factories_from_module(module, module_name=name)
        registry = _merge_factories(registry, factories)

    return registry


def _extract_factories_from_module(
    module: Any, *, module_name: str
) -> dict[str, StepFactory]:
    factories: Mapping[str, Any] | None = None
    if hasattr(module, "pipeline_step_factories"):
        candidate = getattr(module, "pipeline_step_factories")
        if callable(candidate):
            factories = candidate()
        else:
            raise PipelineRegistryError(
                f"pipeline_step_factories in '{module_name}' must be callable."
            )
    elif hasattr(module, "PIPELINE_STEP_FACTORIES"):
        factories = getattr(module, "PIPELINE_STEP_FACTORIES")

    if factories is None:
        raise PipelineRegistryError(
            f"Pipeline step factory module '{module_name}' must expose either "
            "'pipeline_step_factories' or 'PIPELINE_STEP_FACTORIES'."
        )
    if not isinstance(factories, Mapping):
        raise PipelineRegistryError(
            f"Pipeline step factories in '{module_name}' must be a mapping."
        )

    registry: dict[str, StepFactory] = {}
    for key, factory in factories.items():
        name = str(key)
        if not callable(factory):
            raise PipelineRegistryError(
                f"Pipeline step factory '{name}' in '{module_name}' is not callable."
            )
        registry[name] = factory
    return registry


def _discover_entry_point_factories(
    builtin: Mapping[str, StepFactory],
) -> dict[str, StepFactory]:
    loader = plugins.discover_pipeline_step_factories
    signature = inspect.signature(loader)
    supports_builtin = any(
        param.kind is inspect.Parameter.VAR_KEYWORD or param.name == "builtin"
        for param in signature.parameters.values()
    )
    if supports_builtin:
        registry = loader(
            builtin=cast(Mapping[str, PipelineStepFactory], builtin),
        )
        return cast(dict[str, StepFactory], registry)
    registry = loader()
    return _merge_factories(cast(Mapping[str, StepFactory], registry), builtin)


def _merge_factories(
    base: Mapping[str, StepFactory],
    additions: Mapping[str, StepFactory],
) -> dict[str, StepFactory]:
    registry = dict(base)
    for name, factory in additions.items():
        if name in registry:
            raise PipelineRegistryError(
                f"Pipeline step factory '{name}' is already registered."
            )
        registry[name] = factory
    return registry


def collect_pipeline_templates(
    *, template_paths: Sequence[Path] | None = None
) -> tuple[PipelineTemplate, ...]:
    """Return the bundled templates plus any templates loaded from disk."""

    templates = list(list_pipeline_templates())
    if template_paths:
        templates.extend(load_pipeline_templates_from_paths(template_paths))
    return tuple(templates)


def load_pipeline_templates_from_paths(
    paths: Sequence[Path],
) -> tuple[PipelineTemplate, ...]:
    """Load pipeline templates from file or directory paths."""

    templates: list[PipelineTemplate] = []
    for path in _iter_template_files(paths):
        payload = _load_template_manifest(path)
        summary = _coerce_template_summary(payload, source=path)
        description = _coerce_template_description(payload)
        templates.append(
            PipelineTemplate(
                name=path.stem,
                summary=summary,
                description=description,
                manifest=payload,
            )
        )
    return tuple(templates)


def _iter_template_files(paths: Sequence[Path]) -> Iterable[Path]:
    for raw in paths:
        candidate = Path(raw).expanduser()
        if not candidate.exists():
            raise PipelineTemplateLoadError(
                f"Template path '{candidate}' does not exist."
            )
        if candidate.is_dir():
            for item in sorted(candidate.iterdir()):
                if _is_template_file(item):
                    yield item
            continue
        if not _is_template_file(candidate):
            raise PipelineTemplateLoadError(
                f"Template file '{candidate}' must be TOML or YAML."
            )
        yield candidate


def _is_template_file(path: Path) -> bool:
    return path.suffix.lower() in {".toml", ".yaml", ".yml"}


def _load_template_manifest(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix == ".toml":
            data = tomllib.loads(text)
        else:
            data = yaml.safe_load(text) or {}
    except Exception as exc:  # pragma: no cover - parser edge cases
        raise PipelineTemplateLoadError(
            f"Template file '{path}' could not be parsed: {exc}"
        ) from exc

    if not isinstance(data, Mapping):
        raise PipelineTemplateLoadError(
            f"Template file '{path}' must contain a mapping at the top level."
        )

    return dict(data)


def _coerce_template_summary(payload: Mapping[str, Any], *, source: Path) -> str:
    summary = payload.get("summary") or payload.get("description")
    if summary is None:
        return f"Custom template from {source.name}."
    return str(summary).strip() or f"Custom template from {source.name}."


def _coerce_template_description(payload: Mapping[str, Any]) -> str:
    description = payload.get("description")
    if description is None:
        return ""
    return str(description).strip()


@dataclass(slots=True, frozen=True)
class PipelineRegistry:
    """Container for step factory registries and pipeline templates."""

    step_factories: Mapping[str, StepFactory]
    templates: Sequence[PipelineTemplate]

    @classmethod
    def from_defaults(
        cls,
        *,
        module_paths: Sequence[str] | None = None,
        template_paths: Sequence[Path] | None = None,
    ) -> "PipelineRegistry":
        step_factories = build_pipeline_step_factories(module_paths=module_paths)
        templates = collect_pipeline_templates(template_paths=template_paths)
        return cls(step_factories=step_factories, templates=templates)


__all__ = [
    "PipelineRegistry",
    "PipelineRegistryError",
    "PipelineTemplateLoadError",
    "build_pipeline_step_factories",
    "collect_pipeline_templates",
    "load_pipeline_templates_from_paths",
    "load_step_factories_from_modules",
]
