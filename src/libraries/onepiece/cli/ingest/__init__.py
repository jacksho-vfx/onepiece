"""Ingest utility commands."""

import typer

from . import pipeline as _pipeline_module
from . import queue as _queue_module
from . import report as _report_module

app = typer.Typer(name="ingest", help="Tools for analysing ingest inputs")

app.command("report")(_report_module.generate_report)
app.command("add")(_queue_module.ingest_add)
app.command("run")(_queue_module.ingest_run)
app.command("status")(_queue_module.ingest_status)
app.command("plan")(_queue_module.ingest_plan)
app.command("cancel")(_queue_module.ingest_cancel)
app.command("validate")(_queue_module.ingest_validate)
app.add_typer(_pipeline_module.app, name="pipeline")

pipeline = _pipeline_module
queue = _queue_module
report = _report_module

__all__ = ["app", "pipeline", "queue", "report"]
