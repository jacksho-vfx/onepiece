"""Top-level Typer application exposing DCC utilities."""

import typer

from apps.onepiece.dcc.open_shot import app as open_shot
from apps.onepiece.dcc.publish import app as publish
from apps.onepiece.dcc.unreal_import import app as unreal_import


app = typer.Typer(name="dcc", help="DCC integration commands")

app.add_typer(open_shot)
app.add_typer(publish)
app.add_typer(unreal_import)

__all__ = [
    "app",
    "open_shot",
    "publish",
    "unreal_import",
]
