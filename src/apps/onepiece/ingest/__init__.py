"""Ingest utility commands."""

import typer

import apps.onepiece.ingest.report as _report_module

app = typer.Typer(name="ingest", help="Tools for analysing ingest inputs")

app.command("report")(_report_module.generate_report)

report = _report_module

__all__ = ["app", "report"]
