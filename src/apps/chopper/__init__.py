"""Chopper scene renderer and CLI utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .renderer import Frame, Renderer, Scene, SceneObject
from .version import CHOPPER_VERSION, __version__

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from .app import app as app

__all__ = [
    "app",
    "Frame",
    "Renderer",
    "Scene",
    "SceneObject",
    "CHOPPER_VERSION",
    "__version__",
]


def __getattr__(name: str) -> Any:
    """Lazily import :mod:`apps.chopper.app` to avoid circular imports."""

    if name == "app":
        from .app import app as typer_app

        return typer_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
