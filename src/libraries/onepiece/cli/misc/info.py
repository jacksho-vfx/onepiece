"""CLI to display OnePiece environment and configuration info."""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

from typing_extensions import Annotated

try:  # Python 3.8+
    from importlib import metadata
except ImportError:  # pragma: no cover - Python <3.8 fallback
    import importlib_metadata as metadata  # type: ignore

import structlog
import typer

from apps.onepiece.config import load_profile
from libraries.platform.validations.dcc import SupportedDCC

log = structlog.get_logger(__name__)
app = typer.Typer(help="Display environment and configuration info")


def mask_sensitive_value(value: str, visible_chars: int = 4) -> str:
    """Return a masked representation of a potentially sensitive value."""

    if not value or value == "Not set":
        return value

    if len(value) <= visible_chars:
        return "*" * len(value)

    masked_length = len(value) - visible_chars
    return "*" * masked_length + value[-visible_chars:]


def detect_installed_dccs() -> list[str]:
    """Return list of DCCs that are likely installed based on PATH."""
    detected: list[str] = []
    for dcc in SupportedDCC:
        if shutil.which(dcc.command):
            detected.append(dcc.value)
    return detected or ["None detected"]


def _collect_environment_report() -> dict[str, Any]:
    python_version = sys.version.split()[0]

    try:
        onepiece_version = metadata.version("onepiece")
    except metadata.PackageNotFoundError:  # pragma: no cover - not installed
        onepiece_version = "Unknown"

    sg_url = os.environ.get("ONEPIECE_SHOTGRID_URL", "Not set")
    sg_script = os.environ.get("ONEPIECE_SHOTGRID_SCRIPT", "Not set")
    sg_key = os.environ.get("ONEPIECE_SHOTGRID_KEY", "Not set")
    masked_sg_key = mask_sensitive_value(sg_key)
    aws_profile = os.environ.get("AWS_PROFILE", "default")
    dccs = detect_installed_dccs()

    report: dict[str, Any] = {
        "python_version": python_version,
        "onepiece_version": onepiece_version,
        "shotgrid": {
            "url": sg_url,
            "script": sg_script,
            "key": masked_sg_key,
        },
        "aws_profile": aws_profile,
        "detected_dccs": dccs,
    }
    return report


def _render_text_report(report: Mapping[str, Any]) -> None:
    typer.echo("=== OnePiece Environment Info ===")
    typer.echo(f"Python version: {report['python_version']}")
    typer.echo(f"OnePiece version: {report['onepiece_version']}")

    shotgrid = report["shotgrid"]
    typer.echo(f"ShotGrid URL: {shotgrid['url']}")
    typer.echo(f"ShotGrid Script: {shotgrid['script']}")
    typer.echo(f"ShotGrid Key: {shotgrid['key']}")

    typer.echo(f"AWS Profile: {report['aws_profile']}")

    dccs = report["detected_dccs"]
    typer.echo(
        "Detected DCCs: "
        + ", ".join(dccs if isinstance(dccs, list) and dccs else ["None detected"])
    )


@app.command("info")
def info(
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Choose output format (text or json).",
            case_sensitive=False,
        ),
    ] = "text",
) -> None:
    """Print environment and OnePiece configuration information."""

    report = _collect_environment_report()

    log.info(
        "info_report",
        python=report["python_version"],
        onepiece_version=report["onepiece_version"],
        shotgrid_url=report["shotgrid"]["url"],
        shotgrid_script=report["shotgrid"]["script"],
        shotgrid_key=report["shotgrid"]["key"],
        aws_profile=report["aws_profile"],
        dccs=report["detected_dccs"],
    )

    if output_format.lower() == "json":
        typer.echo(json.dumps(report, indent=2, sort_keys=True))
        return

    _render_text_report(report)


@app.command("profile")
def profile(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Override the profile name to load.",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        dir_okay=True,
        file_okay=False,
        resolve_path=True,
        help="Path to a workspace directory that may contain onepiece.toml.",
    ),
    project_root: Optional[Path] = typer.Option(
        None,
        "--project-root",
        dir_okay=True,
        file_okay=False,
        resolve_path=True,
        help="Project root used to discover configuration files.",
    ),
) -> None:
    """Display the resolved configuration profile and its sources."""

    context = load_profile(
        profile=profile, workspace=workspace, project_root=project_root
    )

    typer.echo("=== OnePiece Profile Info ===")
    typer.echo(f"Resolved profile: {context.name}")

    typer.echo("Settings:")
    if context.data:
        for key in sorted(context.data):
            value = context.data[key]
            if isinstance(value, Mapping):
                typer.echo(f"  {key}:")
                for sub_key in sorted(value):
                    typer.echo(f"    {sub_key}: {value[sub_key]}")
            else:
                typer.echo(f"  {key}: {value}")
    else:
        typer.echo("  <none>")

    typer.echo("Configuration sources (lowest to highest precedence):")
    if context.sources:
        for source in context.sources:
            typer.echo(f"  - {source}")
    else:
        typer.echo("  <none>")
