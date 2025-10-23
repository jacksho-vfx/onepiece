"""CLI renderer for DCC environment validation reports."""

from __future__ import annotations

from typing import Iterable, List, Optional

import structlog
import typer

from apps.onepiece.utils.errors import OnePieceValidationError
from libraries.platform.validations.dcc import (
    DCCEnvironmentReport,
    GPUValidation,
    PluginValidation,
    SupportedDCC,
    check_dcc_environment,
)

log = structlog.get_logger(__name__)


def _format_plugins(plugins: PluginValidation) -> str:
    required = ", ".join(sorted(plugins.required)) or "None"
    available = ", ".join(sorted(plugins.available)) or "None"
    missing = ", ".join(sorted(plugins.missing)) or "None"
    return f"required: {required}\n    available: {available}\n    missing: {missing}"


def _format_gpu(gpu: GPUValidation) -> str:
    required = gpu.required or "None"
    detected = gpu.detected or "Not detected"
    status = "meets" if gpu.meets_requirement else "missing"
    return f"required: {required}\n    detected: {detected}\n    status: {status}"


def _render_report(report: DCCEnvironmentReport) -> None:
    header_colour = typer.colors.GREEN if report.installed else typer.colors.YELLOW
    typer.secho(f"{report.dcc.value}", fg=header_colour, bold=True)
    typer.secho(
        f"  Installed : {'yes' if report.installed else 'no'}", fg=header_colour
    )
    typer.secho(
        f"  Executable: {report.executable or 'Not found in PATH'}",
        fg=typer.colors.BLUE if report.executable else typer.colors.YELLOW,
    )
    typer.secho("  Plugins:", fg=typer.colors.CYAN)
    typer.echo("    " + _format_plugins(report.plugins))
    typer.secho("  GPU:", fg=typer.colors.CYAN)
    typer.echo("    " + _format_gpu(report.gpu))


def _has_failures(report: DCCEnvironmentReport) -> bool:
    return (
        (not report.installed)
        or bool(report.plugins.missing)
        or (not report.gpu.meets_requirement)
    )


def render_dcc_environment(
    dcc: Optional[List[SupportedDCC]] = typer.Option(
        None,
        "--dcc",
        help="Specific DCCs to inspect. Defaults to all supported DCCs.",
        case_sensitive=False,
    ),
) -> None:
    """Render environment validation summaries for the requested DCCs."""

    targets: Iterable[SupportedDCC]
    if dcc:
        targets = dcc
    else:
        targets = list(SupportedDCC)

    log.info(
        "validate.dcc_environment.start", targets=[entry.value for entry in targets]
    )

    failures = False
    for entry in targets:
        report = check_dcc_environment(entry)
        _render_report(report)
        typer.echo()
        log.info(
            "validate.dcc_environment.report",
            dcc=entry.value,
            installed=report.installed,
            executable=report.executable,
            plugins_required=sorted(report.plugins.required),
            plugins_available=sorted(report.plugins.available),
            plugins_missing=sorted(report.plugins.missing),
            gpu_required=report.gpu.required,
            gpu_detected=report.gpu.detected,
            gpu_meets=report.gpu.meets_requirement,
        )
        failures = failures or _has_failures(report)

    if failures:
        typer.secho(
            "One or more DCC environments require attention.",
            fg=typer.colors.RED,
        )
        raise OnePieceValidationError(
            "One or more DCC environments require attention. See the summaries above."
        )

    typer.secho("All requested DCC environments look healthy.", fg=typer.colors.GREEN)
    log.info("validate.dcc_environment.success")


__all__ = ["render_dcc_environment"]
