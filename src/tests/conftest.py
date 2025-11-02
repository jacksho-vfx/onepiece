"""Test configuration for Maya unit tests."""

from __future__ import annotations

import sys
import types
from collections.abc import Generator

try:  # pragma: no cover - exercised in tests when Hypothesis is installed
    from hypothesis import HealthCheck, settings
except ModuleNotFoundError:  # pragma: no cover - executed in CI without hypothesis
    class _SettingsStub:
        def register_profile(self, *_args: object, **_kwargs: object) -> None:
            return None

        def load_profile(self, *_args: object, **_kwargs: object) -> None:
            return None

    class _HealthCheckStub:
        too_slow = "too_slow"

    settings = _SettingsStub()  # type: ignore[assignment]
    HealthCheck = _HealthCheckStub()  # type: ignore[assignment]

import pytest

from pytest_mock import MockerFixture


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


@pytest.fixture
def mocker() -> Generator[MockerFixture, None, None]:
    fixture = MockerFixture()
    try:
        yield fixture
    finally:
        fixture.stopall()
