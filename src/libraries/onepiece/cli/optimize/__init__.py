"""Optimization utility commands."""

import typer

from . import commands as _commands

app = typer.Typer(name="optimize", help="Plan and run optimization variants.")
app.command("plan")(_commands.optimize_plan)
app.command("run")(_commands.optimize_run)
app.command("submit")(_commands.optimize_submit)
app.command("report")(_commands.optimize_report)

commands = _commands

__all__ = ["app", "commands"]
