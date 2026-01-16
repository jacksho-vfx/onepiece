"""Shared theme assets for OnePiece web applications."""

from importlib.resources import files
from pathlib import Path

__all__ = ["get_theme_static_directory"]


def get_theme_static_directory() -> Path:
    """Return the directory containing shared web theme assets."""

    resource = files(__name__).joinpath("static")
    return Path(str(resource))
