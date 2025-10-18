"""CLI command to open a scene file in the appropriate DCC."""

from pathlib import Path
from typing import Any

import structlog
import typer

from apps.onepiece.utils.errors import OnePieceExternalServiceError
from libraries.dcc.dcc_client import open_scene
from libraries.validations.dcc import (
    detect_dcc_from_file,
    validate_dcc,
    check_dcc_environment,
)


log = structlog.get_logger(__name__)
app = typer.Typer(help="DCC CLI commands.")


def _resolve_dcc(shot_path: Path, dcc: str | None) -> Any:
    """Return the :class:`SupportedDCC` for ``shot_path``.

    The caller may provide a ``dcc`` name explicitly.  When omitted the value is
    inferred from the file extension which keeps the command convenient for
    day-to-day usage.
    """

    try:
        return validate_dcc(dcc) if dcc else detect_dcc_from_file(shot_path)
    except ValueError as exc:  # pragma: no cover - exercised via the CLI.
        raise typer.BadParameter(str(exc)) from exc


def _format_validation_issues(report: Any) -> list[str]:
    """Return human readable issues extracted from ``report``."""

    issues: list[str] = []

    if not report.installed:
        issues.append("DCC executable is not installed or not found on PATH.")

    missing_plugins = getattr(report.plugins, "missing", frozenset())
    if missing_plugins:
        plugin_list = ", ".join(sorted(missing_plugins))
        issues.append(f"Missing required plugins: {plugin_list}.")

    gpu_report = report.gpu
    if not getattr(gpu_report, "meets_requirement", True):
        required_gpu = getattr(gpu_report, "required", None) or "unspecified"
        detected_gpu = getattr(gpu_report, "detected", None) or "not detected"
        issues.append(
            "GPU requirement not satisfied "
            f"(required: {required_gpu}; detected: {detected_gpu})."
        )

    return issues


@app.command("open-shot")
def open_shot(
    shot_path: Path = typer.Option(
        ...,
        "--shot",
        "-s",
        exists=True,
        file_okay=True,
        help="Path to the shot scene file",
    ),
    dcc: str | None = typer.Option(
        None,
        "--dcc",
        "-d",
        help="Optional DCC name. If omitted, the value is inferred from the file extension.",
    ),
    skip_validation: bool = typer.Option(
        False,
        "--skip-validation",
        help="Skip environment validation checks before opening the scene.",
    ),
) -> None:
    """Open ``shot_path`` with the requested DCC application."""

    dcc_enum = _resolve_dcc(shot_path, dcc)

    if not skip_validation:
        report = check_dcc_environment(dcc_enum)
        issues = _format_validation_issues(report)
        if issues:
            log.error(
                "failed_open_shot.validation",
                dcc=dcc_enum.value,
                shot=str(shot_path),
                issues=issues,
            )
            bullet_list = "\n".join(f"- {entry}" for entry in issues)
            raise OnePieceExternalServiceError(
                "Failed to open "
                f"{shot_path} in {dcc_enum.value}: environment validation failed:\n{bullet_list}"
            )

    try:
        open_scene(dcc_enum, shot_path)
        typer.echo(f"Successfully opened {shot_path} in {dcc_enum.value}")
    except Exception as exc:  # pragma: no cover - surfaced to the CLI.
        log.error(
            "failed_open_shot",
            dcc=dcc_enum.value,
            shot=str(shot_path),
            error=str(exc),
        )
        raise OnePieceExternalServiceError(
            f"Failed to open {shot_path} in {dcc_enum.value}: {exc}"
        ) from exc
