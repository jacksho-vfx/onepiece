"""Top-level Typer application exposing validation helpers."""

import sys

import typer

from . import reconcile as reconcile_module
from .asset_consistency import asset_consistency
from .dcc_environment import render_dcc_environment
from .names import validate_names
from .names_batch import names_batch
from .paths import validate_paths

app = typer.Typer(name="validate", help="Validation commands")

app.command("names")(validate_names)
app.command("names-batch")(names_batch)
app.command("paths")(validate_paths)
app.command("asset-consistency")(asset_consistency)
app.command("dcc-environment")(render_dcc_environment)
app.command("reconcile")(reconcile_module.reconcile)

reconcile = reconcile_module

# Support imports via the legacy ``onepiece`` package namespace.
sys.modules.setdefault("onepiece.validate", sys.modules[__name__])
sys.modules.setdefault("onepiece.validate.reconcile", reconcile_module)


__all__ = ["app", "reconcile"]
