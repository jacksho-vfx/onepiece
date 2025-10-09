"""Chopper scene renderer and CLI utilities."""

from .app import app
from .renderer import Frame, Renderer, Scene, SceneObject
from .version import CHOPPER_VERSION, __version__

__all__ = [
    "app",
    "Frame",
    "Renderer",
    "Scene",
    "SceneObject",
    "CHOPPER_VERSION",
    "__version__",
]
