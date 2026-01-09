"""Input and output helpers for pipeline manifests and parameters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import typer
import yaml

from .clients import PipelineClientError
from .schema import PipelineParameterSchema, PipelineSchemaError, load_pipeline_manifest


try:  # pragma: no cover - Python 3.11+ ships tomllib
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - python<3.11 compatibility
    import tomli as tomllib  # type: ignore[no-redef]


def _parse_pipeline_parameters(
    raw: list[str] | None,
    *,
    base: Mapping[str, Any] | None = None,
    schema: PipelineParameterSchema | None = None,
    interactive: bool = False,
) -> dict[str, Any]:
    parameters: dict[str, Any] = dict(base or {})
    if raw:
        for item in raw:
            if "=" not in item:
                raise PipelineClientError(
                    f"Invalid parameter '{item}'. Expected key=value pairs."
                )
            key, value = item.split("=", 1)
            key = key.strip()
            if not key:
                raise PipelineClientError("Parameter keys cannot be empty.")
            parameters[key] = value.strip()

    if schema is None:
        return parameters

    return _resolve_parameters_with_schema(
        parameters, schema=schema, interactive=interactive
    )


def _load_pipeline_parameters_file(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise PipelineClientError(f"Parameter file '{path}' does not exist.")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - depends on filesystem errors
        raise PipelineClientError(f"Failed to read parameter file: {exc}") from exc

    suffix = path.suffix.lower()

    try:
        if suffix == ".json":
            data = json.loads(text)
        elif suffix == ".toml":
            data = tomllib.loads(text)
        else:
            raise PipelineClientError("Parameter files must use JSON or TOML formats.")
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PipelineClientError(
            f"Parameter file '{path}' is not valid {suffix.lstrip('.') or 'JSON/TOML'}."
        ) from exc

    if not isinstance(data, Mapping):
        raise PipelineClientError(
            "Parameter files must contain a mapping at the top level."
        )

    return dict(data)


def _load_pipeline_submission(
    manifest: Path, *, name: str | None = None
) -> dict[str, Any]:
    try:
        payload = load_pipeline_manifest(manifest)
    except PipelineSchemaError as exc:
        raise typer.BadParameter(str(exc), param_hint="manifest") from exc

    pipelines_section = payload.get("pipelines")
    if isinstance(pipelines_section, Mapping):
        if name is None:
            if len(pipelines_section) != 1:
                raise typer.BadParameter(
                    "Manifest contains multiple pipelines; provide --name to select one.",
                    param_hint="manifest",
                )
            selected_name, config_payload = next(iter(pipelines_section.items()))
        else:
            try:
                config_payload = pipelines_section[name]
            except KeyError as exc:
                raise typer.BadParameter(
                    f"Manifest does not include a pipeline named '{name}'.",
                    param_hint="--name",
                ) from exc
            selected_name = name
        if not isinstance(config_payload, Mapping):
            raise typer.BadParameter(
                "Pipeline entries must be mappings.", param_hint="manifest"
            )
    else:
        raw_name = name or payload.get("name")
        if not raw_name:
            raise typer.BadParameter(
                "Pipeline manifests must declare a 'name'.", param_hint="manifest"
            )
        selected_name = str(raw_name)
        if name is not None and selected_name != name:
            raise typer.BadParameter(
                "Pipeline manifest name does not match the '--name' option "
                f"('{selected_name}' != '{name}').",
                param_hint="--name",
            )
        config_payload = payload

    submission = dict(config_payload)
    submission["name"] = str(selected_name)
    return submission


def _serialised_definition_to_manifest(definition: Mapping[str, Any]) -> dict[str, Any]:
    manifest: dict[str, Any] = {}

    name = definition.get("name")
    if name is not None:
        manifest["name"] = str(name)

    version = definition.get("version")
    if version is not None:
        manifest["version"] = version

    for field in ("display_name", "description"):
        value = definition.get(field)
        if isinstance(value, str) and value.strip():
            manifest[field] = value

    metadata_payload = definition.get("metadata")
    if isinstance(metadata_payload, Mapping):
        metadata_version = metadata_payload.get("version")
        cleaned_metadata = {
            str(key): _normalise_manifest_value(value)
            for key, value in metadata_payload.items()
            if key != "version"
        }
        if cleaned_metadata:
            manifest["metadata"] = cleaned_metadata
        if "version" not in manifest and metadata_version is not None:
            manifest["version"] = metadata_version
    elif metadata_payload is not None:
        manifest["metadata"] = _normalise_manifest_value(metadata_payload)

    parameters = definition.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        manifest["parameters"] = {
            str(key): _normalise_manifest_value(value)
            for key, value in parameters.items()
        }

    steps = definition.get("steps")
    if isinstance(steps, Sequence) and steps:
        sequential_steps: list[dict[str, Any]] = []
        event_triggers: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            manifest_step = _serialised_step_to_manifest(step)
            trigger = step.get("trigger")
            if trigger is None:
                sequential_steps.append(manifest_step)
                continue
            dependencies = _normalise_dependencies(trigger)
            if dependencies:
                manifest_step["after"] = dependencies
            kind = "sequential"
            if isinstance(trigger, Mapping):
                kind = str(trigger.get("kind", "sequential")).lower()
            if kind == "event":
                event_name = (
                    trigger.get("event") if isinstance(trigger, Mapping) else None
                )
                if not isinstance(event_name, str) or not event_name:
                    sequential_steps.append(manifest_step)
                    continue
                trigger_entry: dict[str, Any] = {"on": event_name}
                filters = (
                    trigger.get("filters") if isinstance(trigger, Mapping) else None
                )
                if isinstance(filters, Mapping) and filters:
                    trigger_entry["filters"] = _normalise_manifest_value(filters)
                trigger_entry["steps"] = [manifest_step]
                event_triggers.append(trigger_entry)
            else:
                sequential_steps.append(manifest_step)

        if sequential_steps:
            manifest["steps"] = sequential_steps
        if event_triggers:
            manifest["triggers"] = event_triggers

    return manifest


def _normalise_manifest_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise_manifest_value(val) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalise_manifest_value(item) for item in value]
    return value


def _serialised_step_to_manifest(step: Mapping[str, Any]) -> dict[str, Any]:
    manifest_step: dict[str, Any] = {}

    name = step.get("name")
    manifest_step["id"] = str(name) if name is not None else ""

    provider = step.get("provider")
    manifest_step["uses"] = str(provider) if provider is not None else ""

    config = step.get("config")
    if isinstance(config, Mapping) and config:
        manifest_step["with"] = _normalise_manifest_value(config)

    metadata = step.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        manifest_step["metadata"] = _normalise_manifest_value(metadata)

    return manifest_step


def _normalise_dependencies(trigger: Any) -> list[str]:
    if not isinstance(trigger, Mapping):
        return []
    dependencies = trigger.get("depends_on")
    if dependencies is None:
        return []
    if isinstance(dependencies, Sequence) and not isinstance(
        dependencies, (str, bytes, bytearray)
    ):
        return [str(dep) for dep in dependencies if str(dep)]
    return [str(dependencies)] if str(dependencies) else []


def _write_manifest(path: Path, manifest: Mapping[str, Any], *, format: str) -> None:
    format_normalised = format.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_normalised == "yaml":
        text = yaml.safe_dump(manifest, sort_keys=False)
    elif format_normalised == "toml":
        text = _render_manifest_toml(manifest)
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"Unsupported manifest format: {format}")
    path.write_text(text, encoding="utf-8")


def _write_parameter_template(
    path: Path, template: Mapping[str, Any], *, format: str
) -> None:
    format_normalised = format.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_normalised == "json":
        text = json.dumps(template, indent=2)
    elif format_normalised == "toml":
        text = _render_parameter_template_toml(template)
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"Unsupported parameter template format: {format}")
    path.write_text(text, encoding="utf-8")


def _resolve_manifest_format(output: Path, requested: str | None) -> str:
    if requested:
        candidate = requested.lower()
        if candidate not in {"toml", "yaml"}:
            raise typer.BadParameter(
                "Format must be either 'toml' or 'yaml'.",
                param_hint="--format",
            )
        return candidate

    suffix = output.suffix.lower()
    if suffix == ".toml":
        return "toml"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    return "toml"


def _resolve_parameter_template_format(
    output: Path | None, requested: str | None
) -> str:
    if requested:
        candidate = requested.lower()
        if candidate not in {"json", "toml"}:
            raise typer.BadParameter(
                "Format must be either 'json' or 'toml'.",
                param_hint="--format",
            )
        return candidate

    if output is None:
        return "json"

    suffix = output.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".toml":
        return "toml"
    return "json"


def _render_parameter_template(template: Mapping[str, Any], *, format: str) -> str:
    format_normalised = format.lower()
    if format_normalised == "json":
        return json.dumps(template, indent=2)
    if format_normalised == "toml":
        return _render_parameter_template_toml(template)
    raise ValueError(f"Unsupported parameter template format: {format}")


def _render_parameter_template_toml(template: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for name, value in template.items():
        if not isinstance(value, Mapping):
            lines.append(f"{name} = {_format_toml_scalar(value)}")
            continue
        if lines:
            lines.append("")
        lines.append(f"[{name}]")
        _render_table_body(name, value, lines)
    return "\n".join(lines) + "\n"


def _render_manifest_toml(manifest: Mapping[str, Any]) -> str:
    lines: list[str] = []

    for key, value in manifest.items():
        if key in {"metadata", "parameters", "steps", "triggers"}:
            continue
        if value is None:
            continue
        lines.append(f"{key} = {_format_toml_scalar(value)}")

    metadata = manifest.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        if lines:
            lines.append("")
        lines.append("[metadata]")
        _render_table_body("metadata", metadata, lines)

    parameters = manifest.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        if lines:
            lines.append("")
        for name, definition in parameters.items():
            if not isinstance(definition, Mapping):
                continue
            lines.append(f"[[parameters.{name}]]")
            _render_table_body(f"parameters.{name}", definition, lines)

    steps = manifest.get("steps")
    if isinstance(steps, Sequence) and steps:
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            if lines:
                lines.append("")
            lines.append("[[steps]]")
            _render_table_body("steps", step, lines)

    triggers = manifest.get("triggers")
    if isinstance(triggers, Sequence) and triggers:
        for trigger in triggers:
            if not isinstance(trigger, Mapping):
                continue
            if lines:
                lines.append("")
            lines.append("[[triggers]]")
            _render_table_body("triggers", trigger, lines)

    return "\n".join(lines) + "\n"


def _render_table_body(
    section: str, table: Mapping[str, Any], lines: list[str]
) -> None:
    scalars: list[tuple[str, Any]] = []
    nested_tables: list[tuple[str, Mapping[str, Any]]] = []
    array_tables: list[tuple[str, Sequence[Mapping[str, Any]]]] = []

    for key, value in table.items():
        if value is None:
            continue
        if isinstance(value, Mapping):
            nested_tables.append((key, value))
        elif _is_array_of_tables(value):
            array_tables.append((key, value))
        else:
            scalars.append((key, value))

    for key, value in scalars:
        lines.append(f"{key} = {_format_toml_scalar(value)}")

    for key, value in nested_tables:
        lines.append("")
        lines.append(f"[{section}.{key}]")
        _render_table_body(f"{section}.{key}", value, lines)

    for key, entries in array_tables:
        for entry in entries:
            lines.append("")
            lines.append(f"[[{section}.{key}]]")
            _render_table_body(f"{section}.{key}", entry, lines)


def _is_array_of_tables(value: Any) -> bool:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value) and all(isinstance(item, Mapping) for item in value)
    return False


def _format_toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ", ".join(_format_toml_scalar(item) for item in value) + "]"
    return json.dumps(value)


__all__ = [
    "_format_toml_scalar",
    "_is_array_of_tables",
    "_load_pipeline_parameters_file",
    "_load_pipeline_submission",
    "_normalise_dependencies",
    "_normalise_manifest_value",
    "_parse_pipeline_parameters",
    "_render_parameter_template",
    "_render_parameter_template_toml",
    "_render_manifest_toml",
    "_render_table_body",
    "_resolve_manifest_format",
    "_resolve_parameter_template_format",
    "_serialised_definition_to_manifest",
    "_serialised_step_to_manifest",
    "_write_manifest",
    "_write_parameter_template",
    "_resolve_parameters_with_schema",
]


def _resolve_parameters_with_schema(
    provided: Mapping[str, Any],
    *,
    schema: PipelineParameterSchema,
    interactive: bool,
) -> dict[str, Any]:
    parameters = dict(provided)

    if not schema.parameters:
        return parameters

    try:
        coerced_inputs = schema.coerce(parameters)
    except PipelineSchemaError as exc:
        raise PipelineClientError(str(exc)) from exc

    resolved: dict[str, Any] = dict(coerced_inputs)

    for name, definition in schema.parameters.items():
        if name in resolved:
            continue
        if definition.has_default:
            resolved[name] = definition.default
            continue
        if not definition.required:
            if interactive:
                prompted = _prompt_for_parameter(name, definition)
                if prompted is not None:
                    resolved[name] = prompted
            continue
        if not interactive:
            msg = (
                f"{schema.source} requires parameter '{name}'. Provide a value via"
                " --param, --params-file, or interactively."
            )
            raise PipelineClientError(msg)

        prompted = _prompt_for_parameter(name, definition)
        if prompted is not None:
            resolved[name] = prompted

    return resolved


def _prompt_for_parameter(name: str, definition: Any) -> Any:
    description = getattr(definition, "description", None)
    label = description or f"Value for '{name}'"
    suffix_parts: list[str] = []
    parameter_type = getattr(definition, "type", None)
    choices = getattr(definition, "choices", None)
    if parameter_type:
        suffix_parts.append(str(parameter_type))
    if choices:
        suffix_parts.append("choices: " + ", ".join(map(str, choices)))

    prompt_text = label
    if suffix_parts:
        prompt_text = f"{prompt_text} ({'; '.join(suffix_parts)})"

    default_value = getattr(definition, "default", None)
    has_default = getattr(definition, "has_default", False)
    required = getattr(definition, "required", False)

    while True:
        value = typer.prompt(
            prompt_text,
            default=default_value if has_default else None,
            show_default=has_default,
        )
        if value == "" and not required:
            return None
        if hasattr(definition, "coerce"):
            try:
                return definition.coerce(value)
            except ValueError as exc:  # pragma: no cover - user interaction
                typer.echo(f"Invalid value for '{name}': {exc}")
                continue
        return value
