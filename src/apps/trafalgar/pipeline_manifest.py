"""Helpers for normalising pipeline manifest payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def translate_pipeline_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return *payload* converted to the provider/config schema."""

    if not isinstance(payload, Mapping):
        msg = "pipeline manifest must be a mapping"
        raise TypeError(msg)

    config = dict(payload)
    metadata_payload = config.get("metadata")
    if metadata_payload is None:
        metadata: dict[str, Any] | None = None
    elif isinstance(metadata_payload, Mapping):
        metadata = dict(metadata_payload)
    else:
        msg = "pipeline metadata must be a mapping"
        raise TypeError(msg)

    version = config.pop("version", None)
    if version is not None:
        if metadata is None:
            metadata = {}
        metadata["version"] = version

    if metadata is not None:
        config["metadata"] = metadata

    summary = config.get("summary")
    if summary is not None and "description" not in config:
        config["description"] = str(summary)

    parameters = config.get("parameters")
    if parameters is not None:
        config["parameters"] = _translate_parameters(parameters)

    triggers = config.get("triggers")
    if triggers:
        config["steps"] = _translate_trigger_blocks(triggers)
        config.pop("triggers", None)
    else:
        steps = config.get("steps")
        if steps:
            config["steps"] = _translate_steps(steps)

    return config


def _translate_trigger_blocks(triggers: Any) -> list[dict[str, Any]]:
    if not isinstance(triggers, Sequence):
        msg = "pipeline triggers must be a sequence"
        raise TypeError(msg)

    converted: list[dict[str, Any]] = []
    for trigger in triggers:
        if not isinstance(trigger, Mapping):
            msg = "each trigger entry must be a mapping"
            raise TypeError(msg)

        event = trigger.get("on")
        if not isinstance(event, str) or not event:
            event = trigger.get(True)  # YAML can coerce "on" to True
        if not isinstance(event, str) or not event:
            msg = "event-driven triggers must define a non-empty 'on' event"
            raise ValueError(msg)

        filters = trigger.get("filters") or trigger.get("filter") or {}
        if filters and not isinstance(filters, Mapping):
            msg = "trigger filters must be a mapping"
            raise TypeError(msg)

        steps = trigger.get("steps")
        if not isinstance(steps, Sequence) or not steps:
            msg = "event-driven triggers require a non-empty steps sequence"
            raise ValueError(msg)

        for step in steps:
            converted_step = _translate_step(step)
            trigger_config: dict[str, Any] = {"kind": "event", "event": event}
            if filters:
                trigger_config["filters"] = dict(filters)
            converted_step["trigger"] = trigger_config
            converted.append(converted_step)

    return converted


def _translate_steps(steps: Any) -> list[dict[str, Any]]:
    if not isinstance(steps, Sequence) or not steps:
        msg = "pipeline steps must be a non-empty sequence"
        raise ValueError(msg)

    return [_translate_step(step) for step in steps]


def _translate_parameters(parameters: Any) -> dict[str, Any]:
    if not isinstance(parameters, Mapping):
        msg = "pipeline parameters must be a mapping"
        raise TypeError(msg)

    converted: dict[str, Any] = {}
    for raw_name, raw_definition in parameters.items():
        name = str(raw_name).strip()
        if not name:
            msg = "pipeline parameter names must be non-empty"
            raise ValueError(msg)
        if isinstance(raw_definition, Mapping):
            definition = {str(key): value for key, value in raw_definition.items()}
            translated = dict(definition)
            if "enum" in translated and "choices" not in translated:
                translated["choices"] = _normalise_parameter_choices(
                    translated.pop("enum"), parameter=name
                )
            if "options" in translated and "choices" not in translated:
                translated["choices"] = _normalise_parameter_choices(
                    translated.pop("options"), parameter=name
                )
            if "choices" in translated:
                translated["choices"] = _normalise_parameter_choices(
                    translated["choices"], parameter=name
                )
            if "default" in translated:
                translated["default"] = _normalise_manifest_value(translated["default"])
            if "description" in translated and translated["description"] is not None:
                translated["description"] = str(translated["description"])
            if "type" in translated and translated["type"] is not None:
                translated["type"] = str(translated["type"]).strip()
            converted[name] = translated
        else:
            converted[name] = _normalise_manifest_value(raw_definition)
    return converted


def _normalise_manifest_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise_manifest_value(val) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalise_manifest_value(item) for item in value]
    return value


def _normalise_parameter_choices(value: Any, *, parameter: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        msg = f"pipeline parameter '{parameter}' choices must be a sequence"
        raise TypeError(msg)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value]
    msg = f"pipeline parameter '{parameter}' choices must be a sequence"
    raise TypeError(msg)


def _translate_step(step: Any) -> dict[str, Any]:
    if not isinstance(step, Mapping):
        msg = "pipeline steps must be mappings"
        raise TypeError(msg)

    if "provider" in step and "uses" not in step:
        return _sanitise_provider_step(step)

    provider = step.get("uses") if "uses" in step else step.get("provider")
    if not isinstance(provider, str) or not provider:
        msg = "pipeline steps must define a non-empty 'uses' or 'provider' value"
        raise ValueError(msg)

    step_name = step.get("id") or step.get("name")
    if not isinstance(step_name, str) or not step_name:
        msg = "pipeline steps must define an 'id' or 'name'"
        raise ValueError(msg)

    config_payload = step.get("with") if "with" in step else step.get("config", {})
    if config_payload is None:
        config_payload = {}
    if config_payload and not isinstance(config_payload, Mapping):
        msg = "step configuration must be a mapping when provided"
        raise TypeError(msg)

    metadata = dict(step.get("metadata") or {})
    display_name = step.get("name")
    if display_name and display_name != step_name:
        metadata.setdefault("display_name", str(display_name))
    summary = step.get("summary")
    if summary and "description" not in metadata:
        metadata["description"] = str(summary)

    converted: dict[str, Any] = {
        "name": str(step_name),
        "provider": provider,
    }
    if config_payload:
        converted["config"] = dict(config_payload)
    if metadata:
        converted["metadata"] = metadata

    after = step.get("after")
    if after:
        if isinstance(after, Sequence) and not isinstance(after, (str, bytes)):
            dependencies = [str(dep) for dep in after]
        else:
            dependencies = [str(after)]
        converted["trigger"] = {"kind": "sequential", "depends_on": dependencies}

    return converted


def _sanitise_provider_step(step: Mapping[str, Any]) -> dict[str, Any]:
    converted = dict(step)

    config_payload = converted.get("config")
    if config_payload is None:
        config_payload = {}
    if config_payload and not isinstance(config_payload, Mapping):
        msg = "step configuration must be a mapping when provided"
        raise TypeError(msg)
    if config_payload:
        converted["config"] = dict(config_payload)
    else:
        converted.pop("config", None)

    return converted


__all__ = ["translate_pipeline_manifest"]
