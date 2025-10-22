"""Typer CLI entry points for the Perona dashboard services."""

import json
import os
import shutil
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import typer

from pydantic import ValidationError

from apps.perona.engine import (
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_PNL_BASELINE_COST,
    DEFAULT_SETTINGS_PATH,
    DEFAULT_TARGET_ERROR_RATE,
    PeronaEngine,
)
from apps.perona.models import CostEstimate, CostEstimateRequest, SettingsSummary
from apps.perona.version import PERONA_VERSION

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8065

OutputFormat = Literal["table", "json"]

app = typer.Typer(
    name="perona",
    help=(
        "Operations for the Perona VFX performance dashboard. Use `perona web dashboard` "
        "to launch the FastAPI service that powers the real-time analytics surface."
    ),
)
settings_app = typer.Typer(
    name="settings",
    help="Inspect and manage Perona dashboard settings.",
    invoke_without_command=True,
)
web_app = typer.Typer(name="web", help="Web interface helpers for Perona.")
cost_app = typer.Typer(name="cost", help="Cost modelling utilities for Perona.")
app.add_typer(settings_app)
app.add_typer(web_app)
app.add_typer(cost_app)


@app.command("version")
def version() -> None:
    """Display the current Perona release version."""

    typer.echo(PERONA_VERSION)


def _load_uvicorn() -> Any:
    """Dynamically import uvicorn to keep it optional for non-web commands."""

    try:
        return import_module("uvicorn")
    except ImportError as exc:
        raise typer.BadParameter(
            "uvicorn is required for this command. Install it with "
            "`pip install onepiece[uvicorn]`."
        ) from exc


def _format_value(value: object) -> str:
    """Render numeric values with thousands separators where possible."""

    if isinstance(value, float):
        return f"{value:,}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _humanise_key(key: str) -> str:
    """Convert snake_case keys into a more readable variant."""

    overrides = {"gpu": "GPU", "gb": "GB", "ms": "ms", "pnl": "P&L"}
    words = key.split("_")
    return " ".join(overrides.get(word, word.capitalize()) for word in words)


def _validate_settings_path(settings_path: Path | None) -> Path | None:
    """Ensure an optional settings path exists and is readable."""

    if settings_path is None:
        return None

    resolved = settings_path.expanduser()
    if not resolved.exists():
        raise typer.BadParameter(f"Settings file '{resolved}' does not exist.")
    if not os.access(resolved, os.R_OK):
        raise typer.BadParameter(f"Settings file '{resolved}' is not readable.")

    return resolved


def _format_difference_line(
    label: str,
    entry: Mapping[str, object],
    *,
    width: int,
    indent: str = "",
) -> str:
    """Render a single line describing a deviation from defaults."""

    current = entry.get("current")
    default = entry.get("default")
    delta = entry.get("delta")
    detail_parts: list[str] = []
    if delta is not None:
        delta_display = _format_value(delta)
        if isinstance(delta, (int, float)) and delta > 0:
            delta_display = f"+{delta_display}"
        detail_parts.append(f"Δ {delta_display}")
    if default is not None:
        detail_parts.append(f"default {_format_value(default)}")
    detail = ", ".join(detail_parts)
    suffix = f" ({detail})" if detail else ""
    return f"{indent}{label:<{width}} : {_format_value(current)}{suffix}"


def _diff_numeric(current: object, default: object) -> float | int | None:
    """Return the numeric delta between two values when applicable."""

    numeric_types = (int, float)
    if isinstance(current, numeric_types) and isinstance(default, numeric_types):
        return current - default
    return None


def _diff_mapping(
    current: Mapping[str, object], default: Mapping[str, object]
) -> dict[str, dict[str, object]]:
    """Identify key/value differences between two mappings."""

    differences: dict[str, dict[str, object]] = {}
    for key, value in current.items():
        default_value = default.get(key)
        if value != default_value:
            entry: dict[str, object] = {"current": value, "default": default_value}
            delta = _diff_numeric(value, default_value)
            if delta is not None:
                entry["delta"] = delta
            differences[key] = entry
    return differences


def _calculate_settings_differences(
    baseline: Mapping[str, object],
    target_error_rate: float,
    pnl_baseline_cost: float,
) -> dict[str, object]:
    """Return a structured diff against the baked-in Perona defaults."""

    baseline_defaults = asdict(DEFAULT_BASELINE_COST_INPUT)
    baseline_diffs = _diff_mapping(baseline, baseline_defaults)
    differences: dict[str, object] = {}
    if baseline_diffs:
        differences["baseline_cost_input"] = baseline_diffs

    def _diff_scalar(current: object, default: object) -> dict[str, object] | None:
        if current == default:
            return None
        entry: dict[str, object] = {"current": current, "default": default}
        delta = _diff_numeric(current, default)
        if delta is not None:
            entry["delta"] = delta
        return entry

    target_diff = _diff_scalar(target_error_rate, DEFAULT_TARGET_ERROR_RATE)
    if target_diff is not None:
        differences["target_error_rate"] = target_diff

    pnl_diff = _diff_scalar(pnl_baseline_cost, DEFAULT_PNL_BASELINE_COST)
    if pnl_diff is not None:
        differences["pnl_baseline_cost"] = pnl_diff

    return differences


def _format_settings_table(
    baseline: Mapping[str, object],
    target_error_rate: float,
    pnl_baseline_cost: float,
    *,
    settings_path: Path | None,
    differences: Mapping[str, object] | None = None,
) -> str:
    """Produce a readable summary of the resolved Perona settings."""

    humanised_keys = {key: _humanise_key(key) for key in baseline}
    width = max(
        [len(name) for name in humanised_keys.values()]
        + [len("Target error rate"), len("P&L baseline cost")]
    )
    lines: list[str] = []
    if settings_path is not None:
        lines.append(f"Settings file: {settings_path}")
        lines.append("")
    lines.append("Baseline cost inputs")
    lines.append("-" * len("Baseline cost inputs"))
    for key, value in baseline.items():
        display_key = humanised_keys[key]
        lines.append(f"{display_key:<{width}} : {_format_value(value)}")
    lines.append("")
    lines.append(f"{'Target error rate':<{width}} : {_format_value(target_error_rate)}")
    lines.append(f"{'P&L baseline cost':<{width}} : {_format_value(pnl_baseline_cost)}")

    if differences is not None:
        lines.append("")
        header = "Differences from defaults"
        lines.append(header)
        lines.append("-" * len(header))
        if not differences:
            lines.append("No differences detected (using default settings).")
        else:
            baseline_diffs = differences.get("baseline_cost_input", {})
            if baseline_diffs:
                lines.append("Baseline cost inputs")
                for key in baseline:
                    if key in baseline_diffs:  # type: ignore[operator]
                        display_key = humanised_keys.get(key, _humanise_key(key))
                        lines.append(
                            _format_difference_line(
                                display_key,
                                baseline_diffs[key],  # type: ignore[index]
                                width=width,
                                indent="  ",
                            )
                        )
            if "target_error_rate" in differences:
                lines.append(
                    _format_difference_line(
                        "Target error rate",
                        differences["target_error_rate"],  # type: ignore[arg-type]
                        width=width,
                    )
                )
            if "pnl_baseline_cost" in differences:
                lines.append(
                    _format_difference_line(
                        "P&L baseline cost",
                        differences["pnl_baseline_cost"],  # type: ignore[arg-type]
                        width=width,
                    )
                )
    return "\n".join(lines)


def _format_cost_breakdown_table(estimate: CostEstimate) -> str:
    """Render a tabular summary of the cost estimate."""

    labels = {
        "frame_count": "Frame count",
        "gpu_hours": "GPU hours",
        "render_hours": "Render hours",
        "concurrency": "Concurrency",
        "gpu_cost": "GPU cost",
        "render_farm_cost": "Render farm cost",
        "storage_cost": "Storage cost",
        "egress_cost": "Egress cost",
        "misc_cost": "Misc cost",
        "total_cost": "Total cost",
        "cost_per_frame": "Cost per frame",
    }
    values = estimate.model_dump()
    width = max(len(label) for label in labels.values())
    lines = ["Cost estimate", "-" * len("Cost estimate")]
    for key, label in labels.items():
        lines.append(f"{label:<{width}} : {_format_value(values[key])}")
    return "\n".join(lines)


def _resolve_dashboard_url(explicit_url: str | None) -> str:
    """Return the dashboard URL based on CLI arguments and environment."""

    base = explicit_url or os.getenv("PERONA_DASHBOARD_URL")
    if base:
        return base.rstrip("/")
    return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


def _post_settings_reload(base_url: str) -> SettingsSummary:
    """Trigger the dashboard reload endpoint and return the response summary."""

    endpoint = urljoin(base_url.rstrip("/") + "/", "settings/reload")
    request = Request(endpoint, data=b"", method="POST")
    request.add_header("Content-Length", "0")
    try:
        with urlopen(request) as response:  # type: ignore[call-arg]
            payload = response.read()
            status = getattr(response, "status", response.getcode())
    except HTTPError as exc:  # pragma: no cover - network errors are surfaced in tests
        raise RuntimeError(f"Dashboard returned error: {exc}") from exc
    except URLError as exc:  # pragma: no cover - surfaced in tests when unreachable
        raise RuntimeError(f"Unable to reach dashboard at {endpoint}: {exc.reason}") from exc

    if status != 200:
        raise RuntimeError(f"Dashboard returned unexpected status code {status}.")

    try:
        payload_data = json.loads(payload.decode("utf-8")) if payload else {}
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("Dashboard responded with invalid JSON.") from exc

    try:
        return SettingsSummary.model_validate(payload_data)
    except ValidationError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("Dashboard response did not match the expected schema.") from exc


def _echo_settings_summary(summary: SettingsSummary) -> None:
    """Display a textual summary of the resolved settings."""

    baseline = summary.baseline_cost_input.model_dump()
    typer.echo(
        _format_settings_table(
            baseline,
            summary.target_error_rate,
            summary.pnl_baseline_cost,
            settings_path=summary.settings_path,
        )
    )

    if summary.warnings:
        typer.echo("")
        typer.echo("Warnings:")
        for message in summary.warnings:
            typer.echo(f"- {message}")


@settings_app.callback(invoke_without_command=True)
def settings(
    ctx: typer.Context,
    settings_path: Path | None = typer.Option(
        None,
        "--settings-path",
        help="Optional path to a Perona settings file to load.",
    ),
    diff: bool = typer.Option(
        False,
        "--diff/--no-diff",
        help="Display differences against the bundled defaults.",
    ),
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format for the resolved settings (table or json).",
        case_sensitive=False,
    ),
) -> None:
    """Display the resolved Perona configuration values."""

    if ctx.invoked_subcommand is not None:
        return

    validated_settings_path = _validate_settings_path(settings_path)
    load_result = PeronaEngine.from_settings(path=validated_settings_path)
    engine = load_result.engine
    warnings = load_result.warnings
    resolved_path = load_result.settings_path
    baseline = asdict(engine.baseline_cost_input)
    differences: dict[str, object] | None = None
    payload: dict[str, object] = {
        "baseline_cost_input": baseline,
        "target_error_rate": engine.target_error_rate,
        "pnl_baseline_cost": engine.pnl_baseline_cost,
    }
    if resolved_path is not None:
        payload["settings_path"] = str(resolved_path)
    payload["warnings"] = list(warnings)

    if diff:
        differences = _calculate_settings_differences(
            baseline,
            engine.target_error_rate,
            engine.pnl_baseline_cost,
        )
        payload["differences"] = differences
    elif diff is False:
        differences = None

    fmt = str(output_format).lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("format must be either 'table' or 'json'.")

    if fmt == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            _format_settings_table(
                baseline,
                engine.target_error_rate,
                engine.pnl_baseline_cost,
                settings_path=resolved_path,
                differences=differences if diff else None,
            )
        )

    if warnings:
        typer.echo("")
        typer.echo("Warnings:")
        for message in warnings:
            typer.echo(f"- {message}")

    if warnings:
        raise typer.Exit(code=1)


@settings_app.command("reload")
def settings_reload(
    url: str | None = typer.Option(
        None,
        "--url",
        help=(
            "Base URL of the running Perona dashboard. Defaults to PERONA_DASHBOARD_URL "
            "or http://127.0.0.1:8065."
        ),
    ),
    local: bool = typer.Option(
        False,
        "--local/--no-local",
        help="Reload settings in-process without issuing an HTTP request.",
    ),
) -> None:
    """Force the dashboard engine to reload configuration overrides."""

    if local:
        from apps.perona.web.dashboard import reload_settings

        summary = reload_settings()
        location = "local engine"
    else:
        base_url = _resolve_dashboard_url(url)
        try:
            summary = _post_settings_reload(base_url)
        except RuntimeError as exc:
            typer.echo(f"Error reloading settings via {base_url}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        location = base_url

    typer.echo(f"Settings reloaded via {location}.")
    typer.echo("")
    _echo_settings_summary(summary)

    if summary.warnings:
        raise typer.Exit(code=1)


@cost_app.command("estimate")
def cost_estimate(
    frame_count: int = typer.Option(
        ..., "--frame-count", "-n", help="Total number of frames to render."
    ),
    average_frame_time_ms: float = typer.Option(
        ...,
        "--average-frame-time-ms",
        "-t",
        help="Average render time per frame in milliseconds.",
    ),
    gpu_hourly_rate: float = typer.Option(
        ..., "--gpu-hourly-rate", "-r", help="Hourly GPU cost in the chosen currency."
    ),
    gpu_count: int = typer.Option(
        1, "--gpu-count", "-g", help="Concurrent GPUs utilised for the render."
    ),
    render_hours: float = typer.Option(
        0.0,
        "--render-hours",
        help="Actual render farm hours (defaults to theoretical if omitted).",
    ),
    render_farm_hourly_rate: float = typer.Option(
        0.0,
        "--render-farm-hourly-rate",
        help="Hourly cost for managed render farm usage.",
    ),
    storage_gb: float = typer.Option(
        0.0, "--storage-gb", help="Storage consumed in gigabytes."
    ),
    storage_rate_per_gb: float = typer.Option(
        0.0, "--storage-rate-per-gb", help="Storage cost per gigabyte."
    ),
    data_egress_gb: float = typer.Option(
        0.0, "--data-egress-gb", help="Data egress volume in gigabytes."
    ),
    egress_rate_per_gb: float = typer.Option(
        0.0, "--egress-rate-per-gb", help="Data egress cost per gigabyte."
    ),
    misc_costs: float = typer.Option(
        0.0, "--misc-costs", help="Additional miscellaneous costs."
    ),
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format for the estimate (table or json).",
        case_sensitive=False,
    ),
    settings_path: Path | None = typer.Option(
        None,
        "--settings-path",
        help="Optional path to a Perona settings file to seed defaults.",
    ),
) -> None:
    """Estimate render costs for a given workload."""

    try:
        payload = CostEstimateRequest(
            frame_count=frame_count,
            average_frame_time_ms=average_frame_time_ms,
            gpu_hourly_rate=gpu_hourly_rate,
            gpu_count=gpu_count,
            render_hours=render_hours,
            render_farm_hourly_rate=render_farm_hourly_rate,
            storage_gb=storage_gb,
            storage_rate_per_gb=storage_rate_per_gb,
            data_egress_gb=data_egress_gb,
            egress_rate_per_gb=egress_rate_per_gb,
            misc_costs=misc_costs,
        )
    except ValidationError as exc:
        messages = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", []))
            messages.append(f"{location}: {error.get('msg')}")
        raise typer.BadParameter("; ".join(messages)) from exc

    validated_settings_path = _validate_settings_path(settings_path)
    engine = PeronaEngine.from_settings(path=validated_settings_path).engine
    breakdown = engine.estimate_cost(payload.to_entity())
    estimate = CostEstimate.from_breakdown(breakdown)

    fmt = str(output_format).lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("format must be either 'table' or 'json'.")

    if fmt == "json":
        typer.echo(json.dumps(estimate.model_dump(), indent=2, sort_keys=True))
        return

    typer.echo(_format_cost_breakdown_table(estimate))


@web_app.command("dashboard")
def dashboard(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the dashboard server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the Perona dashboard on.",
        show_default=True,
    ),
    reload: bool = typer.Option(
        False,
        "--reload/--no-reload",
        help="Automatically reload when source files change.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
    settings_path: Path | None = typer.Option(
        None,
        "--settings-path",
        help="Optional path to a Perona settings file loaded by the dashboard.",
    ),
) -> None:
    """Launch the Perona dashboard using uvicorn."""

    typer.echo(f"Starting Perona dashboard on http://{host}:{port}")
    uvicorn = _load_uvicorn()

    validated_settings_path = _validate_settings_path(settings_path)

    if validated_settings_path is not None:
        os.environ["PERONA_SETTINGS_PATH"] = str(validated_settings_path)
    else:
        os.environ.pop("PERONA_SETTINGS_PATH", None)

    uvicorn.run(
        "apps.perona.web.dashboard:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


@app.command("settings-export")
def settings_export(
    destination: Path = typer.Argument(
        ..., help="Path to write the exported Perona settings file to."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite the destination file if it already exists.",
    ),
) -> None:
    """Export the bundled default settings to the provided path."""

    target_path = destination.expanduser()
    parent = target_path.parent
    if not parent.exists() or not parent.is_dir():
        raise typer.BadParameter(
            f"Destination directory '{parent}' does not exist or is not a directory."
        )

    if target_path.exists() and not force:
        raise typer.BadParameter(
            f"Destination file '{target_path}' already exists. Use --force to overwrite."
        )

    shutil.copyfile(DEFAULT_SETTINGS_PATH, target_path)
    typer.echo(f"Exported settings to {target_path}")


__all__ = [
    "app",
    "cost_estimate",
    "dashboard",
    "settings",
    "settings_export",
    "version",
]
