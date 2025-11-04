"""Test configuration for Maya unit tests."""

from __future__ import annotations

import asyncio
import inspect
import sys
import types
from typing import Any
from unittest import mock
from unittest.mock import MagicMock

import pytest

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


def _ensure_pytest_mock_stub() -> None:
    if "pytest_mock" in sys.modules:
        return

    module = types.ModuleType("pytest_mock")

    class MockerFixture:
        def __init__(self) -> None:
            self._patches: list[Any] = []

        def patch(self, target: str) -> object:
            patcher = mock.patch(target, new=MagicMock())
            patched = patcher.start()
            self._patches.append(patcher)
            return patched

        def patch_object(self, target: object, attribute: str) -> object:
            patcher = mock.patch.object(target, attribute, new=MagicMock())
            patched = patcher.start()
            self._patches.append(patcher)
            return patched

        def stopall(self) -> None:
            for patcher in reversed(self._patches):
                patcher.stop()
            self._patches.clear()

        def __getattr__(self, name: str) -> object:
            return getattr(mock, name)

    module.MockerFixture = MockerFixture  # type: ignore[attr-defined]
    module.Mock = mock.Mock  # type: ignore[attr-defined]
    module.MagicMock = mock.MagicMock  # type: ignore[attr-defined]
    module.patch = mock.patch  # type: ignore[attr-defined]
    sys.modules["pytest_mock"] = module


_ensure_pytest_mock_stub()


@pytest.fixture
def mocker(pytestconfig: Any) -> Any:
    module = sys.modules["pytest_mock"]
    fixture = module.MockerFixture(pytestconfig)
    try:
        yield fixture
    finally:
        fixture.stopall()


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        marker = pyfuncitem.get_closest_marker("asyncio")
        if marker is None:
            return None
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(pyfuncitem.obj(**pyfuncitem.funcargs))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
        return True
    return None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "asyncio: mark test as requiring an event loop.")


settings.register_profile(
    "ci",
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("ci")
