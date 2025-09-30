"""Top-level Typer application exposing DCC utilities."""

import typer

from apps.onepiece.dcc.open_shot import app as open_shot
from apps.onepiece.dcc.publish import app as publish


app = typer.Typer(name="dcc", help="DCC integration commands")

app.add_typer(open_shot)
app.add_typer(publish)

__all__ = [
    "app",
    "open_shot",
    "publish",
]
