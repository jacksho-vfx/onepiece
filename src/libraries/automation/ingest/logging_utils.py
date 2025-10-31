"""Logging helpers for the automation ingest package."""

from __future__ import annotations

import logging
from typing import Final


class _StructuredLogger:
    """Very small adapter that mimics :func:`structlog.get_logger`."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def info(self, event: str, **kwargs: object) -> None:
        self._logger.info("%s %s", event, kwargs)

    def warning(self, event: str, **kwargs: object) -> None:
        self._logger.warning("%s %s", event, kwargs)

    def error(self, event: str, **kwargs: object) -> None:
        self._logger.error("%s %s", event, kwargs)


def get_logger(name: str) -> _StructuredLogger:
    """Return a structured logger configured for *name*."""

    logger: Final = logging.getLogger(name)
    return _StructuredLogger(logger)


__all__ = ["_StructuredLogger", "get_logger"]
