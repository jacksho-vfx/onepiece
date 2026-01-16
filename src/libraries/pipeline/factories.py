"""Factories for constructing pipelines from configuration."""

from __future__ import annotations

import sys
from dataclasses import replace
from importlib import import_module
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

from .models import Pipeline, PipelineStep


def pipeline_from_config(config: Mapping[str, Any]) -> Pipeline:
    """Create a :class:`Pipeline` from a mapping configuration."""

    if not isinstance(config, Mapping):
        msg = "pipeline configuration must be a mapping"
        raise TypeError(msg)
    if "name" not in config:
        msg = "pipeline configuration missing 'name'"
        raise KeyError(msg)

    steps_cfg = config.get("steps")
    if not steps_cfg:
        msg = "pipeline configuration requires at least one step"
        raise ValueError(msg)
    if not isinstance(steps_cfg, Sequence):
        msg = "steps configuration must be a sequence"
        raise TypeError(msg)

    steps: list[PipelineStep] = []
    previous_step: str | None = None
    for step_cfg in steps_cfg:
        if not isinstance(step_cfg, Mapping):
            msg = "each step configuration must be a mapping"
            raise TypeError(msg)
        step = PipelineStep.from_config(step_cfg, default_dependency=previous_step)
        steps.append(step)
        previous_step = step.name

    metadata = config.get("metadata", {})
    return Pipeline(name=str(config["name"]), steps=steps, metadata=metadata)


def pipelines_from_config(configs: Iterable[Mapping[str, Any]]) -> tuple[Pipeline, ...]:
    """Create multiple pipelines from an iterable of mapping configurations."""

    return tuple(pipeline_from_config(config) for config in configs)


def _import_provider_module(module_name: str) -> ModuleType:
    """Import *module_name* with compatibility fallbacks."""

    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        if not module_name.startswith("onepiece"):
            raise
        missing = exc.name or ""
        if missing and not module_name.startswith(missing):
            raise
    fallback_name = f"apps.{module_name}"
    module = import_module(fallback_name)
    sys.modules[module_name] = module

    parts = module_name.split(".")
    for length in range(1, len(parts)):
        alias = ".".join(parts[:length])
        target = f"apps.{alias}"
        parent = sys.modules.get(target)
        if parent is not None and alias not in sys.modules:
            sys.modules[alias] = parent

    return module


def resolve_provider(
    reference: Any,
    registry: Mapping[str, Any] | None = None,
) -> Any:
    """Resolve provider references using optional registry and import hooks."""

    if registry and isinstance(reference, str) and reference in registry:
        return registry[reference]

    if not isinstance(reference, str):
        return reference

    module_name: str
    attribute: str
    if ":" in reference:
        module_name, attribute = reference.split(":", 1)
    else:
        module_name, _, attribute = reference.rpartition(".")
        if not module_name:
            msg = (
                "provider references must include a module path using 'module:attribute' "
                "or 'module.attribute'"
            )
            raise ValueError(msg)
    module = _import_provider_module(module_name)
    try:
        resolved = getattr(module, attribute)
    except AttributeError as exc:  # pragma: no cover - defensive guard
        msg = f"module '{module_name}' has no attribute '{attribute}'"
        raise AttributeError(msg) from exc

    if isinstance(resolved, ModuleType):
        for attribute_name in ("app", "reconcile", "handler", "main"):
            candidate = getattr(resolved, attribute_name, None)
            if callable(candidate):
                return candidate
        module_suffix = resolved.__name__.split(".")[-1]
        notifier_name = f"send_{module_suffix}_notification"
        candidate = getattr(resolved, notifier_name, None)
        if callable(candidate):
            return candidate

    return resolved


def with_resolved_providers(
    pipeline: Pipeline,
    registry: Mapping[str, Any] | None = None,
) -> Pipeline:
    """Return a copy of ``pipeline`` with providers resolved via :func:`resolve_provider`."""

    resolved_steps = [
        replace(step, provider=resolve_provider(step.provider, registry=registry))
        for step in pipeline.steps
    ]
    return Pipeline(
        name=pipeline.name, steps=resolved_steps, metadata=pipeline.metadata
    )
