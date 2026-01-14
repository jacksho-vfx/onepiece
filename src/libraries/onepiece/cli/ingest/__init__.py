"""Ingest utility commands."""

import typer

from . import pipeline as _pipeline_module
from . import report as _report_module

app = typer.Typer(name="ingest", help="Tools for analysing ingest inputs")

app.command("report")(_report_module.generate_report)
app.add_typer(_pipeline_module.app, name="pipeline")

pipeline = _pipeline_module
report = _report_module

__all__ = ["app", "pipeline", "report"]
