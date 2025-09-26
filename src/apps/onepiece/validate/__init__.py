"""Top-level Typer application exposing validation helpers."""

import typer

from src.apps.onepiece.validate.names import validate_names
from src.apps.onepiece.validate.names_batch import names_batch
from src.apps.onepiece.validate.paths import validate_paths

app = typer.Typer(name="validate", help="Validation commands for names and paths")

app.command("names")(validate_names)
app.command("names-batch")(names_batch)
app.command("paths")(validate_paths)


__all__ = ["app"]
