"""Web-specific helpers for the Perona CLI."""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any
from urllib.parse import urlparse

import typer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8065
DEFAULT_SETTINGS_RELOAD_TIMEOUT = 5.0
DEFAULT_DEMO_PORT = 18065
SETTINGS_RELOAD_TIMEOUT_ENV = "PERONA_SETTINGS_RELOAD_TIMEOUT"


def _load_uvicorn() -> Any:
    """Dynamically import uvicorn to keep it optional for non-web commands."""

    try:
        return import_module("uvicorn")
    except ImportError as exc:
        raise typer.BadParameter(
            "uvicorn is required for this command. Install it with "
            "`pip install onepiece[uvicorn]`."
        ) from exc


def _resolve_dashboard_url(explicit_url: str | None) -> str:
    """Return the dashboard URL based on CLI arguments and environment."""

    base = explicit_url or os.getenv("PERONA_DASHBOARD_URL")
    if base:
        trimmed = base.strip().rstrip("/")
        parsed = urlparse(trimmed)
        if not parsed.scheme or (parsed.scheme and not parsed.netloc):
            trimmed = f"http://{trimmed}"
        return trimmed
    return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


def _resolve_settings_reload_timeout() -> float:
    """Return the timeout to use for dashboard reload requests."""

    override = os.getenv(SETTINGS_RELOAD_TIMEOUT_ENV)
    if override is None:
        return DEFAULT_SETTINGS_RELOAD_TIMEOUT

    try:
        timeout = float(override)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError(
            f"Environment variable {SETTINGS_RELOAD_TIMEOUT_ENV} must be numeric,"
            f" got '{override}'.",
        ) from exc

    if timeout <= 0:  # pragma: no cover - defensive guard
        raise RuntimeError(
            f"Environment variable {SETTINGS_RELOAD_TIMEOUT_ENV} must be positive,"
            f" got {timeout}.",
        )

    return timeout


__all__ = [
    "DEFAULT_DEMO_PORT",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_SETTINGS_RELOAD_TIMEOUT",
    "SETTINGS_RELOAD_TIMEOUT_ENV",
    "_load_uvicorn",
    "_resolve_dashboard_url",
    "_resolve_settings_reload_timeout",
]
