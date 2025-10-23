import json
from pathlib import Path
from typing import Any

from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient

from apps.trafalgar.web.ingest import (
    IngestRunProvider,
    IngestRunService,
)
from libraries.automation.ingest.registry import IngestRunRegistry

import fastapi.security
import fastapi.security.api_key
import apps.trafalgar.web.security as security
from fastapi.security.http import HTTPAuthorizationCredentials
from apps.trafalgar.web import ingest, render
from apps.trafalgar.web.ingest import app, get_ingest_run_service


class CountingRegistry(IngestRunRegistry):  # type: ignore[misc]
    def __init__(self, path: Path) -> None:
        super().__init__(path=path)
        self.payload_reads = 0

    def _load_payload(self) -> Any:
        self.payload_reads += 1
        return super()._load_payload()


def _write_registry(path: Path, runs: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(runs), encoding="utf-8")


def test_registry_reuses_cached_data_for_missing_runs(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path, [])

    registry = CountingRegistry(path=registry_path)

    assert registry.get("missing") is None
    for _ in range(5):
        assert registry.get("missing") is None

    assert registry.payload_reads == 1


def test_registry_serves_cached_records_when_reload_fails(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    registry_path = tmp_path / "registry.json"
    _write_registry(
        registry_path,
        [
            {
                "id": "run-1",
                "started_at": "2024-02-01T12:00:00Z",
                "completed_at": "2024-02-01T12:05:00Z",
                "report": {"processed": [], "invalid": []},
            }
        ],
    )

    registry = IngestRunRegistry(path=registry_path)
    record = registry.get("run-1")
    assert record is not None

    registry_path.write_text("{", encoding="utf-8")

    def _failing_load(*args: Any, **kwargs: Any) -> None:
        raise json.JSONDecodeError("err", "doc", 0)

    monkeypatch.setattr("libraries.automation.ingest.registry.json.load", _failing_load)

    assert registry.get("run-1") is record


def test_ingest_api_caches_repeated_missing_requests(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Ensure /runs/{id} caches 404 responses and only reloads registry once."""
    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )

    all_roles = set()
    for module in (render, ingest):
        for name in dir(module):
            if name.startswith("ROLE_RENDER_") or name.startswith("ROLE_INGEST_"):
                all_roles.add(getattr(module, name))

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="Bearer",
                roles=all_roles,
            )

        def authenticate_api_key(self, key: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="APIKey",
                roles=all_roles,
            )

    monkeypatch.setattr(
        security, "get_credential_store", lambda *a, **kw: DummyCredentialStore()
    )

    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path, [])

    registry = CountingRegistry(path=registry_path)
    provider = IngestRunProvider(registry=registry)
    service = IngestRunService(provider=provider)

    app.dependency_overrides[get_ingest_run_service] = lambda: service
    client = TestClient(app)

    for _ in range(5):
        response = client.get("/runs/not-here")
        assert response.status_code == 404, response.text

    assert registry.payload_reads == 1

    app.dependency_overrides.clear()
