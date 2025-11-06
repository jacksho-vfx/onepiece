"""Shared fixtures for render CLI tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Generator

import pytest
from typer.testing import CliRunner

from apps.onepiece.render import submit as submit_module


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    """Provide a shared Typer CLI runner for render CLI tests."""
    return CliRunner()


@pytest.fixture(autouse=True)
def _reset_capability_cache() -> Generator[None, None, None]:
    """Ensure the render capability cache is cleared between tests."""
    submit_module._refresh_capabilities_cache()
    yield
    submit_module._refresh_capabilities_cache()


@pytest.fixture
def log_events() -> list[tuple[str, str, dict[str, Any]]]:
    """Collect log events emitted via the captured logger."""
    return []


@pytest.fixture
def event_logger(log_events: list[tuple[str, str, dict[str, Any]]]) -> SimpleNamespace:
    """Create a logger namespace that records log messages into ``log_events``."""

    def _record(level: str, event: str, **kwargs: Any) -> None:
        log_events.append((level, event, kwargs))

    return SimpleNamespace(
        info=lambda event, **kwargs: _record("info", event, **kwargs),
        warning=lambda event, **kwargs: _record("warning", event, **kwargs),
        error=lambda event, **kwargs: _record("error", event, **kwargs),
        exception=lambda event, **kwargs: _record("exception", event, **kwargs),
    )
