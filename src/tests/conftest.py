"""Test configuration for Maya unit tests."""

from __future__ import annotations

import sys
import types

from hypothesis import HealthCheck, settings


def _ensure_structlog_stub() -> None:
    if "structlog" in sys.modules:
        return

    structlog = types.ModuleType("structlog")

    class _StubLogger:
        def bind(self, *args: object, **kwargs: object) -> "_StubLogger":
            return self

        def new(self, *args: object, **kwargs: object) -> "_StubLogger":
            return self

        def debug(self, *args: object, **kwargs: object) -> None:
            return None

        info = warning = error = debug

    def _get_logger(*_args: object, **_kwargs: object) -> _StubLogger:
        return _StubLogger()

    structlog.get_logger = _get_logger  # type: ignore[attr-defined]
    structlog.getLogger = _get_logger  # type: ignore[attr-defined]
    sys.modules["structlog"] = structlog


_ensure_structlog_stub()

settings.register_profile(
    "ci",
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("ci")
