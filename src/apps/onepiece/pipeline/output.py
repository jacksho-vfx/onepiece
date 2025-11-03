"""Formatting helpers for pipeline CLI output."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

import typer


_MISSING = object()


def _format_parameter_default(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _format_parameter_choices(values: Sequence[Any] | None) -> str | None:
    if not values:
        return None
    formatted = [_format_parameter_default(value) for value in values]
    return ", ".join(formatted)


def _normalise_parameter_definition(
    value: Any,
) -> tuple[bool, Any, str | None, str | None, tuple[Any, ...] | None]:
    required = False
    default: Any = _MISSING
    description: str | None = None
    param_type: str | None = None
    choices: tuple[Any, ...] | None = None
    if isinstance(value, Mapping):
        if "required" in value:
            required = bool(value.get("required"))
        if "default" in value:
            default = value.get("default")
        raw_description = value.get("description")
        if isinstance(raw_description, str):
            stripped = raw_description.strip()
            if stripped:
                description = stripped
        raw_type = value.get("type")
        if isinstance(raw_type, str):
            stripped_type = raw_type.strip()
            if stripped_type:
                param_type = stripped_type
        raw_choices = value.get("choices")
        if isinstance(raw_choices, Sequence) and not isinstance(
            raw_choices, (str, bytes, bytearray)
        ):
            choices = tuple(raw_choices)
    else:
        default = value
    return required, default, description, param_type, choices


def _format_pipeline_definition(definition: Mapping[str, Any]) -> Iterable[str]:
    name = str(definition.get("name", ""))
    display = definition.get("display_name")
    display_text = str(display).strip() if display is not None else ""
    description = definition.get("description")

    if display_text and display_text != name:
        yield f"{name} ({display_text})"
    else:
        yield name

    if isinstance(description, str) and description.strip():
        yield f"  Description: {description.strip()}"

    parameters = definition.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        summaries: list[str] = []
        for key in sorted(parameters):
            required, default, _, param_type, choices = _normalise_parameter_definition(
                parameters[key]
            )
            details: list[str] = []
            if param_type:
                details.append(f"type={param_type}")
            if choices:
                formatted_choices = _format_parameter_choices(choices)
                if formatted_choices:
                    details.append(f"choices={formatted_choices}")
            if required:
                details.append("required")
            if default is not _MISSING:
                details.append(f"default={_format_parameter_default(default)}")
            label = key
            if details:
                label = f"{key} (" + ", ".join(details) + ")"
            summaries.append(label)
        if summaries:
            yield "  Parameters: " + ", ".join(summaries)


def _render_pipeline_details(definition: Mapping[str, Any]) -> None:
    name = str(definition.get("name", ""))
    typer.echo(f"Name: {name}")

    display = definition.get("display_name")
    display_text = str(display).strip() if display is not None else ""
    if display_text and display_text != name:
        typer.echo(f"Display name: {display_text}")

    description = definition.get("description")
    if isinstance(description, str) and description.strip():
        typer.echo(f"Description: {description.strip()}")

    parameters = definition.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        typer.echo("Parameters:")
        for key in sorted(parameters):
            required, default, description, param_type, choices = (
                _normalise_parameter_definition(parameters[key])
            )
            details: list[str] = []
            if param_type:
                details.append(f"type={param_type}")
            if required:
                details.append("required")
            if default is not _MISSING:
                details.append(f"default={_format_parameter_default(default)}")
            suffix = f" ({', '.join(details)})" if details else ""
            typer.echo(f"  - {key}{suffix}")
            if description:
                typer.echo(f"      {description}")
            formatted_choices = _format_parameter_choices(choices)
            if formatted_choices:
                typer.echo(f"      Choices: {formatted_choices}")
    else:
        typer.echo("Parameters: <none>")


def _format_pipeline_run(run: Mapping[str, Any]) -> Iterable[str]:
    run_id = str(run.get("id", ""))
    pipeline = str(run.get("pipeline", ""))
    status = str(run.get("status", ""))
    created = str(run.get("created_at", ""))
    updated = str(run.get("updated_at", ""))

    yield f"Run {run_id}"
    yield f"  Pipeline: {pipeline}"
    yield f"  Status: {status}"
    yield f"  Created: {created}"
    yield f"  Updated: {updated}"

    initiator = _coerce_display_text(run.get("submitted_by"))
    if initiator:
        yield f"  Submitted by: {initiator}"
        role_list = _normalise_roles(run.get("roles"))
        if role_list:
            yield "  Roles: " + ", ".join(role_list)

    parameters = run.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        yield "  Parameters:"
        for key in sorted(parameters):
            value = parameters[key]
            typer_line = f"    - {key}: {value}"
            yield typer_line
    else:
        yield "  Parameters: <none>"


def _format_run_event(event: Mapping[str, Any]) -> Iterable[str]:
    timestamp = str(event.get("timestamp", ""))
    status = str(event.get("status", ""))
    pipeline = str(event.get("pipeline", ""))
    yield f"[{timestamp}] {pipeline} - {status}"

    parameters = event.get("parameters")
    if isinstance(parameters, Mapping) and parameters:
        yield from _format_event_parameters(parameters)


def _format_event_parameters(parameters: Mapping[str, Any]) -> Iterable[str]:
    step_name = _coerce_display_text(parameters.get("step"))
    if step_name:
        yield f"  Step: {step_name}"

    event_metadata = parameters.get("event")
    if isinstance(event_metadata, Mapping) and event_metadata:
        event_name = _coerce_display_text(event_metadata.get("name"))
        if event_name:
            yield f"  Trigger event: {event_name}"
        payload = event_metadata.get("payload")
        if payload not in (None, {}):
            formatted = json.dumps(payload, sort_keys=True)
            yield f"  Trigger payload: {formatted}"

    error_message = _coerce_display_text(parameters.get("error_message"))
    error_type = _coerce_display_text(parameters.get("error_type"))
    error_fallback = _coerce_display_text(parameters.get("error"))
    if error_message and error_type:
        yield f"  Error: {error_message} ({error_type})"
    elif error_message:
        yield f"  Error: {error_message}"
    elif error_type and error_fallback:
        yield f"  Error: {error_fallback} ({error_type})"
    elif error_fallback:
        yield f"  Error: {error_fallback}"
    elif error_type:
        yield f"  Error: {error_type}"

    traceback_value = parameters.get("traceback")
    traceback_lines: list[str] = []
    if isinstance(traceback_value, str):
        traceback_lines = traceback_value.splitlines()
    elif isinstance(traceback_value, Sequence) and not isinstance(
        traceback_value, (str, bytes, bytearray)
    ):
        traceback_lines = [str(line).rstrip("\n") for line in traceback_value]

    if traceback_lines:
        yield "  Traceback:"
        for line in traceback_lines:
            if line:
                yield f"    {line}"
            else:
                yield ""

    ignored_keys = {
        "step",
        "event",
        "error",
        "error_type",
        "error_message",
        "traceback",
    }
    extras = [
        (str(key), parameters[key]) for key in parameters if key not in ignored_keys
    ]
    if extras:
        yield "  Parameters:"
        for key, value in sorted(extras, key=lambda item: item[0]):
            yield f"    - {key}: {value}"


def _coerce_display_text(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return ""


def _normalise_roles(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items: Iterable[str] = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        items = value
    else:
        return []
    seen: set[str] = set()
    roles: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        roles.append(text)
    return sorted(roles)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_pipeline_statistics(stats: Mapping[str, Any]) -> Iterable[str]:
    pipelines = stats.get("pipelines")
    if not isinstance(pipelines, Mapping) or not pipelines:
        return []

    lines: list[str] = []
    for pipeline in sorted(pipelines):
        lines.append(f"Pipeline: {pipeline}")
        statuses = pipelines[pipeline]
        if not isinstance(statuses, Mapping) or not statuses:
            lines.append("  No runs recorded.")
            continue
        for status in sorted(statuses):
            entry = statuses[status]
            count = entry.get("count", 0)
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                count_int = 0
            plural = "s" if count_int != 1 else ""
            line = f"  {status}: {count_int} run{plural}"
            durations = entry.get("durations")
            if isinstance(durations, Mapping):
                average = durations.get("average_seconds")
                minimum = durations.get("min_seconds")
                maximum = durations.get("max_seconds")
                if all(
                    isinstance(value, (int, float))
                    for value in (average, minimum, maximum)
                ):
                    line += (
                        f" (avg {float(average):.2f}s, min {float(minimum):.2f}s, "  # type: ignore[arg-type]
                        f"max {float(maximum):.2f}s)"  # type: ignore[arg-type]
                    )
            lines.append(line)
    return lines


def _format_worker_metrics(metrics: Mapping[str, Any]) -> str:
    active = metrics.get("active_workers")
    try:
        active_workers = int(active)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        active_workers = 0

    limit_value = metrics.get("max_workers")
    if limit_value is None:
        limit_display = "unbounded"
    else:
        try:
            limit_display = str(int(limit_value))
        except (TypeError, ValueError):
            limit_display = str(limit_value)

    return f"Active workers: {active_workers} (limit: {limit_display})."


def _format_pipeline_prune_summary(result: Mapping[str, Any]) -> Iterable[str]:
    removed_runs = _coerce_int(result.get("removed_runs"))
    removed_events = _coerce_int(result.get("removed_events"))
    remaining_runs = _coerce_int(result.get("remaining_runs"))
    lines = [
        f"Removed {removed_runs} runs and {removed_events} events from the store.",
        f"{remaining_runs} runs remain after pruning.",
    ]

    removed_by_pipeline = result.get("removed_runs_by_pipeline")
    if isinstance(removed_by_pipeline, Mapping) and removed_by_pipeline:
        details = ", ".join(
            f"{pipeline}: {_coerce_int(count)}"
            for pipeline, count in sorted(removed_by_pipeline.items())
        )
        lines.append(f"Per-pipeline removals: {details}.")

    policy_parts: list[str] = []
    max_age_seconds = result.get("max_age_seconds")
    if isinstance(max_age_seconds, (int, float)):
        hours = float(max_age_seconds) / 3600
        policy_parts.append(f"max age {hours:.2f} hours")
    max_runs = result.get("max_runs")
    if isinstance(max_runs, (int, float)):
        policy_parts.append(f"max runs {int(max_runs)}")
    if policy_parts:
        lines.append("Retention applied: " + ", ".join(policy_parts) + ".")

    return lines


__all__ = [
    "_coerce_display_text",
    "_coerce_int",
    "_format_event_parameters",
    "_format_parameter_choices",
    "_format_parameter_default",
    "_format_pipeline_definition",
    "_format_pipeline_prune_summary",
    "_format_pipeline_run",
    "_format_pipeline_statistics",
    "_format_run_event",
    "_format_worker_metrics",
    "_normalise_parameter_definition",
    "_normalise_roles",
    "_render_pipeline_details",
]
