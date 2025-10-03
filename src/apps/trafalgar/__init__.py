"""Trafalgar dashboard utilities and CLI entry points."""

from apps.trafalgar.app import app, web_app
from . import web as web  # re-export for convenience

__all__ = ["app", "web", "web_app"]
