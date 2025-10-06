"""Trafalgar dashboard utilities and CLI entry points."""

from apps.trafalgar.app import app, web_app
from . import web as web
from .version import TRAFALGAR_VERSION, __version__

__all__ = ["app", "web", "web_app", "TRAFALGAR_VERSION", "__version__"]
