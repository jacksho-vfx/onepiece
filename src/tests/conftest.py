"""Shared pytest fixtures for Trafalgar web application tests."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Iterator

import pytest

try:  # pragma: no cover - exercised implicitly during test discovery
    import structlog
except (
    ModuleNotFoundError
):  # pragma: no cover - exercised implicitly during test discovery
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

    structlog.get_logger = _get_logger
    structlog.getLogger = _get_logger
    sys.modules["structlog"] = structlog

try:  # pragma: no cover - exercised implicitly during test discovery
    from apps.trafalgar.web import security
except (
    ModuleNotFoundError
):  # pragma: no cover - exercised implicitly during test discovery
    security = None


@pytest.fixture(autouse=True)
def configure_security(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configure deterministic credentials for integration tests."""

    if security is None:
        pytest.skip("Trafalgar web dependencies are not available in this environment.")

    credentials = [
        {
            "id": "test-suite",
            "key": "suite-key",
            "secret": "suite-secret",
            "roles": [
                security.ROLE_RENDER_READ,
                security.ROLE_RENDER_SUBMIT,
                security.ROLE_RENDER_MANAGE,
                security.ROLE_INGEST_READ,
                security.ROLE_REVIEW_READ,
            ],
        },
        {
            "id": "render-read",
            "key": "render-read-key",
            "secret": "render-read-secret",
            "roles": [security.ROLE_RENDER_READ],
        },
        {
            "id": "ingest-read",
            "key": "ingest-read-key",
            "secret": "ingest-read-secret",
            "roles": [security.ROLE_INGEST_READ],
        },
        {
            "id": "review-client",
            "token": "review-token",
            "roles": [security.ROLE_REVIEW_READ],
        },
    ]

    monkeypatch.setenv(security.CREDENTIALS_ENV, json.dumps(credentials))
    security.reset_security_state()
    try:
        yield
    finally:
        security.reset_security_state()
