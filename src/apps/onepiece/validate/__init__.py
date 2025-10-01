"""Top-level Typer application exposing validation helpers."""

import typer

from apps.onepiece.validate.asset_consistency import asset_consistency
from apps.onepiece.validate.dcc_environment import render_dcc_environment
from apps.onepiece.validate.names import validate_names
from apps.onepiece.validate.names_batch import names_batch
from apps.onepiece.validate.paths import validate_paths

app = typer.Typer(name="validate", help="Validation commands")

app.command("names")(validate_names)
app.command("names-batch")(names_batch)
app.command("paths")(validate_paths)
app.command("asset-consistency")(asset_consistency)
app.command("dcc-environment")(render_dcc_environment)


__all__ = ["app"]
