"""Minimal stub of :mod:`upath` providing :class:`UPath` for tests."""

from __future__ import annotations


class UPath(str):
    def __init__(self):  # type: ignore[no-untyped-def]
        self.parent = None

    """Simple string subclass used as a stand-in for the external library."""

    # No additional behaviour is required for the current test-suite usage.
    pass
