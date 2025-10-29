"""Configuration helpers shared between render adapters."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Mapping


@lru_cache(maxsize=None)
def get_adapter_settings(adapter: str) -> Mapping[str, str]:
    """Return adapter settings sourced from environment variables."""

    prefix = f"RENDER_{adapter.upper()}_"
    settings: dict[str, str] = {}
    for name, value in os.environ.items():
        if name.startswith(prefix):
            settings[name[len(prefix) :].lower()] = value
    return settings


def get_adapter_setting(
    adapter: str, key: str, default: str | None = None
) -> str | None:
    """Return a single adapter setting value, falling back to ``default`` when missing."""

    settings = get_adapter_settings(adapter)
    return settings.get(key.lower(), default)


__all__ = ["get_adapter_setting", "get_adapter_settings"]
