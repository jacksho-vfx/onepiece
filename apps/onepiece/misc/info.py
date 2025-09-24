"""
CLI to display OnePiece environment and configuration info.
"""

import sys
import os
import typer
import structlog

from onepiece.validations.dcc import SupportedDCC

log = structlog.get_logger(__name__)
app = typer.Typer(help="Display environment and configuration info")


def detect_installed_dccs() -> list[str]:
    """Return list of DCCs that are likely installed based on PATH."""
    detected = []
    for dcc in SupportedDCC:
        if dcc.value.lower() in os.environ.get("PATH", "").lower():
            detected.append(dcc.value)
    return detected or ["None detected"]


@app.command("info")
def info():
    """
    Print environment and OnePiece configuration information.
    """
    typer.echo("=== OnePiece Environment Info ===")
    typer.echo(f"Python version: {sys.version.split()[0]}")
    typer.echo(f"OnePiece version: 0.1")
    
    sg_url = os.environ.get("SHOTGRID_URL", "Not set")
    typer.echo(f"ShotGrid URL: {sg_url}")
    
    aws_profile = os.environ.get("AWS_PROFILE", "default")
    typer.echo(f"AWS Profile: {aws_profile}")
    
    dccs = detect_installed_dccs()
    typer.echo(f"Detected DCCs: {', '.join(dccs)}")
    
    log.info(
        "info_report",
        python=sys.version,
        shotgrid_url=sg_url,
        aws_profile=aws_profile,
        dccs=dccs
    )

