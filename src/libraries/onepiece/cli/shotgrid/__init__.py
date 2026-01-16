"""Aggregate Typer application for ShotGrid related commands."""

import typer

from .deliver import app as deliver
from .flow_setup import app as flow_setup
from .package_playlist import app as package_playlist
from .templates import app as templates
from .upload_version import app as upload_version
from .version_zero import app as version_zero

app = typer.Typer(name="shotgrid", help="Shotgrid related commands.")

app.add_typer(deliver)
app.add_typer(flow_setup)
app.add_typer(package_playlist)
app.add_typer(templates)
app.add_typer(upload_version)
app.add_typer(version_zero)

__all__ = [
    "app",
    "deliver",
    "flow_setup",
    "package_playlist",
    "templates",
    "upload_version",
    "version_zero",
]
