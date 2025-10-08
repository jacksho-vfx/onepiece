"""Shared pytest fixtures for Trafalgar web application tests."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from apps.trafalgar.web import security


@pytest.fixture(autouse=True)
def configure_security(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configure deterministic credentials for integration tests."""

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
