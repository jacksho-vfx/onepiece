"""Top-level Typer application exposing DCC utilities."""

from typing import Any

import structlog
import typer

from apps.onepiece.dcc.animation import app as animation
from apps.onepiece.dcc.cinema4d import app as cinema4d
from apps.onepiece.dcc.nuke import app as nuke
from apps.onepiece.dcc.open_shot import app as open_shot
from apps.onepiece.dcc.publish import app as publish
from apps.onepiece.dcc.unreal_import import app as unreal_import


log = structlog.get_logger(__name__)

app = typer.Typer(name="dcc", help="DCC integration commands")

app.add_typer(animation)
app.add_typer(cinema4d)
app.add_typer(nuke)
app.add_typer(open_shot)
app.add_typer(publish)
app.add_typer(unreal_import)


def conform(*, profile: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """Record conform operations initiated by pipeline automation."""

    log.info("dcc.conform", profile=profile)
    return {"profile": profile, "parameters": dict(kwargs)}


__all__ = [
    "app",
    "animation",
    "cinema4d",
    "nuke",
    "open_shot",
    "publish",
    "unreal_import",
    "conform",
]
