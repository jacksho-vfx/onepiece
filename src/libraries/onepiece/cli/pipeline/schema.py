"""Shared helpers for pipeline manifest and parameter schemas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from apps.trafalgar.pipeline.parameters import (
    ParameterDefinition,
    _parse_parameter_definitions,
)

try:  # pragma: no cover - Python 3.11+ ships tomllib
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - python<3.11 compatibility
    import tomli as tomllib  # type: ignore[no-redef]


class PipelineSchemaError(RuntimeError):
    """Raised when manifest or parameter schemas are invalid."""


def load_pipeline_manifest(path: Path) -> Mapping[str, Any]:
    """Return the parsed manifest payload from *path*.

    TOML and YAML manifests are supported; a :class:`PipelineSchemaError` is
    raised for unknown formats or invalid payloads.
    """

    if not path.exists():
        msg = f"Pipeline manifest '{path}' does not exist."
        raise PipelineSchemaError(msg)

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    try:
        if suffix == ".toml":
            data = tomllib.loads(text)
        elif suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore[import-untyped]
            except ImportError as exc:  # pragma: no cover - optional dependency
                msg = "PyYAML is required to load YAML pipeline manifests."
                raise PipelineSchemaError(msg) from exc
            data = yaml.safe_load(text) or {}
        else:
            msg = "Pipeline manifests must use TOML or YAML formats."
            raise PipelineSchemaError(msg)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        msg = f"Pipeline manifest '{path}' could not be parsed: {exc}"
        raise PipelineSchemaError(msg) from exc

    if not isinstance(data, Mapping):
        msg = "Pipeline manifests must contain a mapping at the top level."
        raise PipelineSchemaError(msg)

    return dict(data)


@dataclass(frozen=True, slots=True)
class PipelineParameterSchema:
    """Parameter definitions with helpers for defaults and templates."""

    parameters: Mapping[str, ParameterDefinition]
    source: str

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any] | None, *, source: str
    ) -> "PipelineParameterSchema":
        parsed = _parse_parameter_definitions(payload, location=source)
        return cls(parameters=parsed, source=source)

    def coerce(self, provided: Mapping[str, Any]) -> dict[str, Any]:
        """Coerce *provided* values to the schema types.

        Unknown parameters or invalid values raise :class:`PipelineSchemaError`.
        """

        unknown = [name for name in provided if name not in self.parameters]
        if unknown:
            details = ", ".join(sorted(unknown))
            msg = f"{self.source} does not define parameters: {details}"
            raise PipelineSchemaError(msg)

        coerced: dict[str, Any] = {}
        for name, definition in self.parameters.items():
            if name not in provided:
                continue
            try:
                coerced[name] = definition.coerce(provided[name])
            except ValueError as exc:
                msg = f"{self.source} parameter '{name}' could not be validated: {exc}"
                raise PipelineSchemaError(msg) from exc
        return coerced

    def example_template(self) -> Mapping[str, Any]:
        """Return an example parameter mapping suitable for docs/templates."""

        template: dict[str, Any] = {}
        for name, definition in sorted(self.parameters.items()):
            example_value = _example_value_for_parameter(definition, name=name)
            entry: dict[str, Any] = {
                "required": definition.required,
                "example": example_value,
            }
            if definition.description:
                entry["description"] = definition.description
            if definition.type:
                entry["type"] = definition.type
            if definition.has_default:
                entry["default"] = definition.default
            if definition.choices:
                entry["choices"] = list(definition.choices)
            template[name] = entry
        return template


def _example_value_for_parameter(definition: ParameterDefinition, *, name: str) -> Any:
    if definition.has_default:
        return definition.default
    if definition.choices:
        return definition.choices[0]
    type_name = (definition.type or "string").lower()
    if type_name == "integer":
        return 1
    if type_name == "number":
        return 1.0
    if type_name == "boolean":
        return True
    return f"<{name}>"


__all__ = [
    "PipelineParameterSchema",
    "PipelineSchemaError",
    "_example_value_for_parameter",
    "load_pipeline_manifest",
]
