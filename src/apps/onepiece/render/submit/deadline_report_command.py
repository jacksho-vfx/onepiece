"""Deadline reporting command for formatted notifications."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import typer

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceRuntimeError,
)
from libraries.automation.render.deadline import (
    DeadlineAuthenticationError,
    DeadlineResponseError,
    DeadlineUnavailableError,
    get_report,
)


_DEFAULT_REPORT_ENDPOINT = "api/reports/summary"
_DATE_MARKERS = ("date", "timestamp", "time")


@dataclass(frozen=True)
class DeadlineReport:
    """Normalized Deadline report contents."""

    usage: Mapping[str, Any]
    optimization: Mapping[str, Any]
    recommendations: tuple[str, ...]
    raw: Mapping[str, Any]


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, val in value.items():
            if "deadline" in str(key).lower():
                continue
            sanitized[key] = _sanitize_payload(val)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_payload(entry) for entry in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in _DATE_MARKERS):
            return "<omitted>"
        if "-" in value and value[:4].isdigit():
            return "<omitted>"
        if "t" in value and ":" in value:
            return "<omitted>"
    return value


def _collect_section(payload: Mapping[str, Any], keys: Iterable[str]) -> Mapping[str, Any]:
    for key in keys:
        section = payload.get(key)
        if isinstance(section, Mapping):
            return section
    return {}


def _extract_recommendations(payload: Mapping[str, Any]) -> tuple[str, ...]:
    candidates = ("recommendations", "improvements", "suggestions", "advice")
    for key in candidates:
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(str(item) for item in value if item)
        if isinstance(value, str) and value.strip():
            return (value.strip(),)
    return ()


def _format_metric_value(value: Any) -> str | None:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value)}"
        return f"{value:.2f}"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _metric_lines(source: Mapping[str, Any], label_map: Mapping[str, str]) -> list[str]:
    lines: list[str] = []
    for key, label in label_map.items():
        formatted = _format_metric_value(source.get(key))
        if formatted is not None:
            lines.append(f"- {label}: {formatted}")
    return lines


def _bar(value: float | None) -> str | None:
    if value is None:
        return None
    clamped = max(0.0, min(100.0, value))
    blocks = int(round(clamped / 10.0))
    return "█" * blocks + "░" * (10 - blocks) + f" {clamped:.0f}%"


def _coerce_percent(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().rstrip("%")
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return None
    return None


def _build_report(payload: Mapping[str, Any]) -> DeadlineReport:
    sanitized = _sanitize_payload(payload)
    usage = _collect_section(sanitized, ("usage", "utilization", "capacity"))
    optimization = _collect_section(sanitized, ("optimization", "optimisation", "tuning"))
    recommendations = _extract_recommendations(sanitized)
    return DeadlineReport(
        usage=usage,
        optimization=optimization,
        recommendations=recommendations,
        raw=sanitized,
    )


def _render_email(report: DeadlineReport) -> str:
    usage_labels = {
        "total_jobs": "Total jobs",
        "active_workers": "Active workers",
        "idle_workers": "Idle workers",
        "queue_depth": "Queue depth",
        "utilization_percent": "Utilization (%)",
        "gpu_utilization_percent": "GPU utilization (%)",
        "render_hours": "Render hours",
    }
    optimization_labels = {
        "avg_frame_time_ms": "Average frame time (ms)",
        "avg_render_time_ms": "Average render time (ms)",
        "cache_hit_rate": "Cache hit rate",
        "retry_rate": "Retry rate",
        "resubmits": "Resubmits",
        "success_rate_percent": "Success rate (%)",
    }

    lines = [
        "Deadline render manager report",
        "",
        "Usage snapshot",
    ]
    lines.extend(_metric_lines(report.usage, usage_labels) or ["- No usage metrics available."])
    lines.append("")
    lines.append("Optimisation snapshot")
    lines.extend(
        _metric_lines(report.optimization, optimization_labels)
        or ["- No optimisation metrics available."]
    )
    lines.append("")
    lines.append("Recommendations")
    if report.recommendations:
        lines.extend(f"- {entry}" for entry in report.recommendations)
    else:
        lines.append("- No recommendations provided.")
    return "\n".join(lines)


def _render_teams(report: DeadlineReport) -> str:
    usage_summary = _metric_lines(
        report.usage,
        {
            "active_workers": "Active workers",
            "queue_depth": "Queue depth",
            "utilization_percent": "Utilization (%)",
        },
    )
    optimization_summary = _metric_lines(
        report.optimization,
        {
            "avg_frame_time_ms": "Avg frame time (ms)",
            "cache_hit_rate": "Cache hit rate",
            "success_rate_percent": "Success rate (%)",
        },
    )
    recs = report.recommendations[:3]

    lines = ["Deadline report highlights"]
    lines.append("Usage: " + (", ".join(line[2:] for line in usage_summary) or "n/a"))
    lines.append(
        "Optimization: " + (", ".join(line[2:] for line in optimization_summary) or "n/a")
    )
    if recs:
        lines.append("Recommendations: " + "; ".join(recs))
    else:
        lines.append("Recommendations: none")
    return "\n".join(lines)


def _render_visual(report: DeadlineReport) -> str:
    utilization = _coerce_percent(report.usage.get("utilization_percent"))
    gpu_util = _coerce_percent(report.usage.get("gpu_utilization_percent"))
    visual_lines = ["Usage visualisation"]
    utilization_bar = _bar(utilization)
    if utilization_bar:
        visual_lines.append(f"- Utilization: {utilization_bar}")
    else:
        visual_lines.append("- Utilization: n/a")
    gpu_bar = _bar(gpu_util)
    if gpu_bar:
        visual_lines.append(f"- GPU utilization: {gpu_bar}")
    else:
        visual_lines.append("- GPU utilization: n/a")
    return "\n".join(visual_lines)


def deadline_report(
    *,
    endpoint: str = typer.Option(
        _DEFAULT_REPORT_ENDPOINT,
        "--endpoint",
        help="Deadline API endpoint to query for reporting data.",
    ),
    format: str = typer.Option(
        "all",
        "--format",
        help="Output format: all, email, teams, visual, or json.",
    ),
) -> None:
    """Gather Deadline reports and format them for notifications."""

    try:
        payload = get_report(endpoint)
    except DeadlineAuthenticationError as exc:
        raise OnePieceExternalServiceError(str(exc)) from exc
    except DeadlineUnavailableError as exc:
        raise OnePieceExternalServiceError(str(exc)) from exc
    except DeadlineResponseError as exc:
        raise OnePieceExternalServiceError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        raise OnePieceRuntimeError("Deadline reporting failed.") from exc

    report = _build_report(payload if isinstance(payload, Mapping) else {})
    chosen = format.lower().strip()
    if chosen == "json":
        typer.echo(json.dumps(report.raw, indent=2, sort_keys=True))
        return

    sections: list[str] = []
    if chosen in {"all", "email"}:
        sections.append(_render_email(report))
    if chosen in {"all", "teams"}:
        sections.append(_render_teams(report))
    if chosen in {"all", "visual"}:
        sections.append(_render_visual(report))

    if not sections:
        raise OnePieceRuntimeError(
            "Unsupported format requested. Use all, email, teams, visual, or json."
        )

    typer.echo("\n\n".join(sections))


__all__ = ["deadline_report"]
