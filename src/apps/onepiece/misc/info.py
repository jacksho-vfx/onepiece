"""CLI to display OnePiece environment and configuration info."""

import os
import sys

try:  # Python 3.8+
    from importlib import metadata
except ImportError:  # pragma: no cover - Python <3.8 fallback
    import importlib_metadata as metadata  # type: ignore

import structlog
import typer

from src.libraries.validations.dcc import SupportedDCC

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
    detected = []
    for dcc in SupportedDCC:
        if dcc.value.lower() in os.environ.get("PATH", "").lower():
            detected.append(dcc.value)
    return detected or ["None detected"]


@app.command("info")
def info() -> None:
    """
    Print environment and OnePiece configuration information.
    """
    typer.echo("=== OnePiece Environment Info ===")
    python_version = sys.version.split()[0]
    typer.echo(f"Python version: {python_version}")

    try:
        onepiece_version = metadata.version("onepiece")
    except metadata.PackageNotFoundError:  # pragma: no cover - not installed
        onepiece_version = "Unknown"
    typer.echo(f"OnePiece version: {onepiece_version}")

    sg_url = os.environ.get("ONEPIECE_SHOTGRID_URL", "Not set")
    typer.echo(f"ShotGrid URL: {sg_url}")

    sg_script = os.environ.get("ONEPIECE_SHOTGRID_SCRIPT", "Not set")
    typer.echo(f"ShotGrid Script: {sg_script}")

    sg_key = os.environ.get("ONEPIECE_SHOTGRID_KEY", "Not set")
    masked_sg_key = mask_sensitive_value(sg_key)
    typer.echo(f"ShotGrid Key: {masked_sg_key}")

    aws_profile = os.environ.get("AWS_PROFILE", "default")
    typer.echo(f"AWS Profile: {aws_profile}")

    dccs = detect_installed_dccs()
    typer.echo(f"Detected DCCs: {', '.join(dccs)}")

    log.info(
        "info_report",
        python=python_version,
        onepiece_version=onepiece_version,
        shotgrid_url=sg_url,
        shotgrid_script=sg_script,
        shotgrid_key=masked_sg_key,
        aws_profile=aws_profile,
        dccs=dccs,
    )
