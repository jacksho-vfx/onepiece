"""Integration tests for the Trafalgar authentication layer."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
import pytest

from apps.trafalgar.web import ingest, render, review, security


def _api_headers(key: str, secret: str) -> dict[str, str]:
    settings = security.get_security_settings()
    return {settings.api_key_header: key, settings.api_secret_header: secret}


def test_render_requires_authentication() -> None:
    with TestClient(render.app) as client:
        response = client.get("/health")
        assert response.status_code == 401


def test_render_rejects_requests_missing_role() -> None:
    headers = _api_headers("ingest-read-key", "ingest-read-secret")
    with TestClient(render.app) as client:
        response = client.get("/health", headers=headers)
        assert response.status_code == 403


def test_ingest_health_allows_authorised_client() -> None:
    headers = _api_headers("suite-key", "suite-secret")
    with TestClient(ingest.app) as client:
        response = client.get("/health", headers=headers)
        assert response.status_code == 200


def test_review_accepts_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyClient:
        def list_playlists(
            self, project: str
        ) -> list[dict[str, str]]:  # pragma: no cover - simple stub
            return [{"playlist_name": "Dailies"}]

    def _dummy_versions(client: DummyClient, project: str, playlist: str) -> list[Any]:
        return []

    monkeypatch.setattr(review, "fetch_playlist_versions", _dummy_versions)

    with TestClient(review.app) as client:
        client.app.dependency_overrides[review.get_shotgrid_client] = (
            lambda: DummyClient()
        )
        response = client.get(
            "/projects/example/playlists",
            headers={"Authorization": "Bearer review-token"},
        )
        assert response.status_code == 200
