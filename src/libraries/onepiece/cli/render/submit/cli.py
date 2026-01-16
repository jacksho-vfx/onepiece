"""Typer application wiring for render submission commands."""

from __future__ import annotations

import typer

from ..reporting_command import generate_weekly_report
from .cancel_command import cancel_render_job
from .helpers import FARM_ADAPTERS
from .optimize_deadline_command import optimize_and_submit_deadline
from .presets import (
    export_preset,
    import_preset,
    list_presets,
    save_preset,
    use_preset,
)
from .scripts_command import generate_scripts
from .status_command import render_status
from .submit_command import submit

app = typer.Typer(name="render", help="Render farm submission and management commands.")
presets_app = typer.Typer(name="preset", help="Manage render submission presets.")

app.command("submit")(submit)
app.command("optimize-deadline")(optimize_and_submit_deadline)
app.command("status")(render_status)
app.command("cancel")(cancel_render_job)
app.command("scripts")(generate_scripts)
app.command("report-weekly")(generate_weekly_report)

presets_app.command("list")(list_presets)
presets_app.command("save")(save_preset)
presets_app.command("use")(use_preset)
presets_app.command("export")(export_preset)
presets_app.command("import")(import_preset)

app.add_typer(presets_app, name="preset")

__all__ = ["FARM_ADAPTERS", "app", "presets_app"]
