"""Minimal stub of :mod:`structlog` for local testing.

This project only relies on ``get_logger`` providing objects with ``info`` and
``error`` methods, so the shim wraps the standard :mod:`logging` module to
provide compatible behaviour without requiring the real dependency.
"""

from __future__ import annotations

import logging
from typing import Any


class _Logger:
    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def info(self, event: str, **kwargs: Any) -> None:
        self._logger.info("%s %s", event, kwargs if kwargs else "")

    def error(self, event: str, **kwargs: Any) -> None:
        self._logger.error("%s %s", event, kwargs if kwargs else "")


def get_logger(name: str) -> _Logger:
    return _Logger(name)


__all__ = ["get_logger"]
