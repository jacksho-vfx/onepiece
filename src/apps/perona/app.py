"""Typer CLI entry points for the Perona dashboard services."""

import json
import os
import shutil
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

import typer
from pydantic import ValidationError

from apps.perona.cli.formatting import (
    SettingsDifferences,
    _calculate_settings_differences,
    _format_cost_breakdown_table,
    _format_cost_insights,
    _format_risk_heatmap,
    _format_settings_table,
)
from apps.perona.cli.web import (
    DEFAULT_DEMO_PORT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    _load_uvicorn,
    _resolve_dashboard_url,
    _resolve_settings_reload_timeout,
)
from apps.perona.notifications import (
    NotificationDispatchError,
    dispatch_render_volatility_alert,
)
from apps.perona.version import PERONA_VERSION
from apps.perona.web.dashboard import dependencies as dashboard_dependencies
from apps.perona.web.wrangler.scripts.production import _build_render_volatility_report
from libraries.analytics.perona.engine.engine import PeronaEngine
from libraries.analytics.perona.engine.models import SUPPORTED_CURRENCIES
from libraries.analytics.perona.engine.settings import DEFAULT_SETTINGS_PATH
from libraries.analytics.perona.models import (
    CostEstimate,
    CostEstimateRequest,
)
from libraries.analytics.perona.models import RiskIndicator as RiskIndicatorModel
from libraries.analytics.perona.models import (
    SettingsSummary,
)

OutputFormat = Literal["table", "json"]

RISK_HEATMAP_TOP_LIMIT = 100
METRICS_PATH_ENV = "PERONA_METRICS_PATH"

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
risk_app = typer.Typer(name="risk", help="Risk analytics utilities for Perona.")
app.add_typer(settings_app)
app.add_typer(web_app)
app.add_typer(cost_app)
app.add_typer(risk_app)


@app.command("version")
def version() -> None:
    """Display the current Perona release version."""

    typer.echo(PERONA_VERSION)


def _validate_settings_path(settings_path: Path | None) -> Path | None:
    """Ensure an optional settings path exists and is readable."""

    if settings_path is None:
        return None

    resolved = settings_path.expanduser()
    if not resolved.exists():
        raise typer.BadParameter(f"Settings file '{resolved}' does not exist.")
    if not resolved.is_file():
        raise typer.BadParameter(f"Settings path '{resolved}' must be a file.")
    if not os.access(resolved, os.R_OK):
        raise typer.BadParameter(f"Settings file '{resolved}' is not readable.")

    return resolved


def _validate_metrics_path(metrics_path: Path) -> None:
    """Ensure the metrics path resolves to a writable file location."""

    if metrics_path.exists() and metrics_path.is_dir():
        raise typer.BadParameter(
            f"Metrics path '{metrics_path}' points to a directory; expected a file."
        )

    parent = metrics_path.parent
    existing_parent = parent
    while not existing_parent.exists():
        if existing_parent.parent == existing_parent:  # pragma: no cover - defensive
            break
        existing_parent = existing_parent.parent

    if existing_parent.exists() and not existing_parent.is_dir():
        raise typer.BadParameter(
            f"Metrics path parent '{existing_parent}' is not a directory."
        )

    if existing_parent.exists() and not os.access(existing_parent, os.W_OK):
        raise typer.BadParameter(
            f"Metrics directory '{existing_parent}' is not writable."
        )


def _post_settings_reload(base_url: str) -> SettingsSummary:
    """Trigger the dashboard reload endpoint and return the response summary."""

    parsed = urlparse(base_url)
    path = parsed.path or "/"
    combined_path = urljoin(path.rstrip("/") + "/", "settings/reload")
    endpoint = urlunparse(parsed._replace(path=combined_path, fragment=""))
    request = Request(endpoint, data=b"", method="POST")
    request.add_header("Content-Length", "0")
    timeout = _resolve_settings_reload_timeout()
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status = getattr(response, "status", response.getcode())
    except HTTPError as exc:  # pragma: no cover - network errors are surfaced in tests
        raise RuntimeError(f"Dashboard returned error: {exc}") from exc
    except URLError as exc:  # pragma: no cover - surfaced in tests when unreachable
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)) or (
            isinstance(reason, str) and "timed out" in reason.lower()
        ):
            raise RuntimeError(
                f"Dashboard request timed out after {timeout} seconds."
            ) from exc
        raise RuntimeError(
            f"Unable to reach dashboard at {endpoint}: {exc.reason}"
        ) from exc

    if status != 200:
        raise RuntimeError(f"Dashboard returned unexpected status code {status}.")

    try:
        payload_data = json.loads(payload.decode("utf-8")) if payload else {}
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("Dashboard responded with invalid JSON.") from exc

    try:
        return SettingsSummary.model_validate(payload_data)
    except ValidationError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError(
            "Dashboard response did not match the expected schema."
        ) from exc


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


@app.command("metrics-path")
def metrics_path() -> None:
    """Display and validate the configured render metrics path."""

    resolved_path = dashboard_dependencies.metrics_store_path()
    env_override = os.getenv(METRICS_PATH_ENV)

    _validate_metrics_path(resolved_path)

    typer.echo(f"Active metrics path: {resolved_path}")
    if env_override:
        typer.echo(
            f"Environment override detected: {METRICS_PATH_ENV}={env_override}"  # noqa: E501
        )
    else:
        typer.echo(
            "No PERONA_METRICS_PATH override detected; using XDG cache fallback."
        )


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
    ignore_warnings_exit_zero: bool = typer.Option(
        False,
        "--ignore-warnings-exit-zero",
        help=(
            "Suppress non-zero exit codes when settings warnings are emitted."
            " Warnings still print to stdout."
        ),
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
    differences: SettingsDifferences | None = None
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
                differences=differences,
            )
        )

    if warnings:
        typer.echo("")
        typer.echo("Warnings:")
        for message in warnings:
            typer.echo(f"- {message}")

    if warnings and not ignore_warnings_exit_zero:
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
    frame_count: int | None = typer.Option(
        None, "--frame-count", "-n", help="Total number of frames to render."
    ),
    average_frame_time_ms: float | None = typer.Option(
        None,
        "--average-frame-time-ms",
        "-t",
        help="Average render time per frame in milliseconds.",
    ),
    gpu_hourly_rate: float | None = typer.Option(
        None,
        "--gpu-hourly-rate",
        "-r",
        help="Hourly GPU cost in the chosen currency.",
    ),
    gpu_count: int | None = typer.Option(
        None, "--gpu-count", "-g", help="Concurrent GPUs utilised for the render."
    ),
    render_hours: float | None = typer.Option(
        None,
        "--render-hours",
        help="Actual render farm hours (defaults to theoretical if omitted).",
    ),
    render_farm_hourly_rate: float | None = typer.Option(
        None,
        "--render-farm-hourly-rate",
        help="Hourly cost for managed render farm usage.",
    ),
    storage_gb: float | None = typer.Option(
        None, "--storage-gb", help="Storage consumed in gigabytes."
    ),
    storage_rate_per_gb: float | None = typer.Option(
        None, "--storage-rate-per-gb", help="Storage cost per gigabyte."
    ),
    data_egress_gb: float | None = typer.Option(
        None, "--data-egress-gb", help="Data egress volume in gigabytes."
    ),
    egress_rate_per_gb: float | None = typer.Option(
        None, "--egress-rate-per-gb", help="Data egress cost per gigabyte."
    ),
    misc_costs: float | None = typer.Option(
        None, "--misc-costs", help="Additional miscellaneous costs."
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
    currency: str | None = typer.Option(
        None,
        "--currency",
        help=(
            "Currency code for monetary values. Supported codes: "
            + ", ".join(SUPPORTED_CURRENCIES)
        ),
        case_sensitive=False,
    ),
) -> None:
    """Estimate render costs for a given workload."""

    validated_settings_path = _validate_settings_path(settings_path)
    settings_result = PeronaEngine.from_settings(path=validated_settings_path)
    engine = settings_result.engine
    baseline = engine.baseline_cost_input

    payload_data = {
        "frame_count": frame_count if frame_count is not None else baseline.frame_count,
        "average_frame_time_ms": (
            average_frame_time_ms
            if average_frame_time_ms is not None
            else baseline.average_frame_time_ms
        ),
        "gpu_hourly_rate": (
            gpu_hourly_rate if gpu_hourly_rate is not None else baseline.gpu_hourly_rate
        ),
        "gpu_count": gpu_count if gpu_count is not None else baseline.gpu_count,
        "render_hours": (
            render_hours if render_hours is not None else baseline.render_hours
        ),
        "render_farm_hourly_rate": (
            render_farm_hourly_rate
            if render_farm_hourly_rate is not None
            else baseline.render_farm_hourly_rate
        ),
        "storage_gb": storage_gb if storage_gb is not None else baseline.storage_gb,
        "storage_rate_per_gb": (
            storage_rate_per_gb
            if storage_rate_per_gb is not None
            else baseline.storage_rate_per_gb
        ),
        "data_egress_gb": (
            data_egress_gb if data_egress_gb is not None else baseline.data_egress_gb
        ),
        "egress_rate_per_gb": (
            egress_rate_per_gb
            if egress_rate_per_gb is not None
            else baseline.egress_rate_per_gb
        ),
        "misc_costs": misc_costs if misc_costs is not None else baseline.misc_costs,
        "currency": currency if currency is not None else baseline.currency,
    }

    try:
        payload = CostEstimateRequest(**payload_data)
    except ValidationError as exc:
        messages = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", []))
            messages.append(f"{location}: {error.get('msg')}")
        raise typer.BadParameter("; ".join(messages)) from exc

    breakdown = engine.estimate_cost(payload.to_entity())
    estimate = CostEstimate.from_breakdown(breakdown)

    fmt = str(output_format).lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("format must be either 'table' or 'json'.")

    if fmt == "json":
        typer.echo(json.dumps(estimate.model_dump(), indent=2, sort_keys=True))
        return

    typer.echo(_format_cost_breakdown_table(estimate))


@cost_app.command("insights")
def cost_insights(
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format for the insights (table or json).",
        case_sensitive=False,
    ),
    settings_path: Path | None = typer.Option(
        None,
        "--settings-path",
        help="Optional path to a Perona settings file to seed defaults.",
    ),
    top: int | None = typer.Option(
        None,
        "--top",
        "-n",
        help="Limit the number of optimisation recommendations (1-10).",
    ),
) -> None:
    """Summarise telemetry statistics and cost optimisation recommendations."""

    validated_settings_path = _validate_settings_path(settings_path)
    settings_result = PeronaEngine.from_settings(path=validated_settings_path)
    engine = settings_result.engine
    if top is not None:
        if top < 1 or top > 10:
            raise typer.BadParameter("top must be between 1 and 10.")
        statistics, recommendations = engine.cost_insights(top_n=top)
    else:
        statistics, recommendations = engine.cost_insights()

    fmt = str(output_format).lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("format must be either 'table' or 'json'.")

    if fmt == "json":
        payload = {
            "statistics": [asdict(entry) for entry in statistics],
            "recommendations": list(recommendations),
        }
        if settings_result.settings_path is not None:
            payload["settings_path"] = str(settings_result.settings_path)  # type: ignore[assignment]
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    typer.echo(
        _format_cost_insights(
            statistics,
            recommendations,
            settings_path=settings_result.settings_path,
        )
    )


@risk_app.command("heatmap")
def risk_heatmap(
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format for the risk heatmap (table or json).",
        case_sensitive=False,
    ),
    settings_path: Path | None = typer.Option(
        None,
        "--settings-path",
        help="Optional path to a Perona settings file to seed defaults.",
    ),
    top: int | None = typer.Option(
        None,
        "--top",
        "-n",
        help=("Limit the number of indicators shown (1-100, highest risk first)."),
    ),
) -> None:
    """Display the highest risk shots from the Perona telemetry heatmap."""

    validated_settings_path = _validate_settings_path(settings_path)
    settings_result = PeronaEngine.from_settings(path=validated_settings_path)
    engine = settings_result.engine

    if top is not None and (top < 1 or top > RISK_HEATMAP_TOP_LIMIT):
        raise typer.BadParameter(f"top must be between 1 and {RISK_HEATMAP_TOP_LIMIT}.")

    indicators = tuple(engine.risk_heatmap())
    total_count = len(indicators)
    if top is not None:
        indicators = indicators[:top]

    fmt = str(output_format).lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("format must be either 'table' or 'json'.")

    if fmt == "json":
        payload: dict[str, object] = {
            "indicators": [
                RiskIndicatorModel.from_entity(indicator).model_dump()
                for indicator in indicators
            ],
            "total_indicators": total_count,
        }
        if settings_result.settings_path is not None:
            payload["settings_path"] = str(settings_result.settings_path)
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    indicator_models = tuple(
        RiskIndicatorModel.from_entity(indicator) for indicator in indicators
    )
    typer.echo(
        _format_risk_heatmap(
            indicator_models,
            settings_path=settings_result.settings_path,
            total_count=total_count,
        )
    )


@risk_app.command("volatility")
def render_volatility(
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format for the volatility hotspots (table or json).",
        case_sensitive=False,
    ),
    settings_path: Path | None = typer.Option(
        None,
        "--settings-path",
        help="Optional path to a Perona settings file to seed defaults.",
    ),
    notify: bool = typer.Option(
        False,
        "--notify/--no-notify",
        help="Send the volatility headline to configured webhook URLs.",
        show_default=True,
    ),
) -> None:
    """Surface volatility hotspots derived from render frame time telemetry."""

    validated_settings_path = _validate_settings_path(settings_path)
    settings_result = PeronaEngine.from_settings(path=validated_settings_path)
    engine = settings_result.engine

    headline, hotspots = _build_render_volatility_report(engine)
    payload: dict[str, object] = {"headline": headline, "volatility": hotspots}

    fmt = str(output_format).lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("format must be either 'table' or 'json'.")

    if notify:
        try:
            dispatched = dispatch_render_volatility_alert(headline, hotspots)
        except NotificationDispatchError as exc:
            typer.echo(f"Notification failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        payload["notification_dispatched"] = dispatched

    if fmt == "json":
        if settings_result.settings_path is not None:
            payload["settings_path"] = str(settings_result.settings_path)
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    typer.echo(headline)
    if hotspots:
        typer.echo("")
        for entry in hotspots:
            variance = entry.get("variance") or {}
            coeff = None
            if isinstance(variance, Mapping):
                coeff = variance.get("coefficient_of_variation")
            avg_ms = None
            if isinstance(variance, Mapping):
                avg_ms = variance.get("average_frame_time_ms")
            avg_display = (
                f"{float(avg_ms):.3f}" if isinstance(avg_ms, (int, float)) else "?"
            )
            coeff_display = (
                f"{float(coeff):.4f}" if isinstance(coeff, (int, float)) else "?"
            )
            sequence = entry.get("sequence", "?")
            shot = entry.get("shot", "?")
            risk = float(entry.get("risk_score", 0.0) or 0.0)

            typer.echo(
                f"- {sequence} {shot}: risk {risk:.1f}, frame time {avg_display}ms, coeff {coeff_display}"
            )

    if notify:
        if payload.get("notification_dispatched"):
            typer.echo("Notification dispatched via configured webhooks.")
        else:
            typer.echo("No webhook URLs configured; skipped notification.")


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


@web_app.command("demo")
def demo_dashboard(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the demo dashboard server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_DEMO_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the Perona demo dashboard on.",
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
) -> None:
    """Launch the static Perona demo dashboard using uvicorn."""

    typer.echo(f"Starting Perona demo dashboard on http://{host}:{port}")
    uvicorn = _load_uvicorn()

    uvicorn.run(
        "apps.perona.web.dummy_dashboard:app",
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
    "cost_insights",
    "dashboard",
    "demo_dashboard",
    "metrics_path",
    "settings",
    "settings_export",
    "version",
]
