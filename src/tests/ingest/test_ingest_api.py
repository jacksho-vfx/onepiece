from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient

from apps.trafalgar.web.ingest import (
    IngestRunProvider,
    IngestRunService,
)
from libraries.ingest.registry import IngestRunRecord
from libraries.ingest.service import IngestReport, IngestedMedia, MediaInfo
import fastapi.security
import fastapi.security.api_key
import apps.trafalgar.web.security as security
from fastapi.security.http import HTTPAuthorizationCredentials
from apps.trafalgar.web.ingest import app, get_ingest_run_service
from apps.trafalgar.web import render, ingest


class DummyIngestProvider(IngestRunProvider):  # type: ignore[misc]
    def __init__(self, records: list[IngestRunRecord]):
        super().__init__()
        self._records = records

    def load_recent_runs(self, limit: int | None = None) -> list[IngestRunRecord]:
        if limit is None:
            return list(self._records)
        return list(self._records)[:limit]

    def get_run(self, run_id: str) -> IngestRunRecord:
        for record in self._records:
            if record.run_id == run_id:
                return record
        return None


def _make_record(run_id: str = "abc123") -> IngestRunRecord:
    report = IngestReport(
        processed=[
            IngestedMedia(
                path=Path("/mnt/incoming/show/episode/scene/shot.mov"),
                bucket="vendor_in",
                key="show/episode/scene/shot.mov",
                media_info=MediaInfo(
                    show_code="OP",
                    episode="E001",
                    scene="S001",
                    shot="SH001",
                    descriptor="final",
                    extension="mov",
                ),
            )
        ],
        invalid=[
            (
                Path("/mnt/incoming/invalid_file.mov"),
                "Descriptor must be provided in the filename",
            )
        ],
    )
    return IngestRunRecord(
        run_id=run_id,
        started_at=datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 12, 45, tzinfo=timezone.utc),
        report=report,
    )


def test_list_runs_serialises_registry_records(monkeypatch: MonkeyPatch) -> None:
    """Ensure /runs endpoint serialises ingest registry records correctly."""
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

    provider = DummyIngestProvider([_make_record()])
    service = IngestRunService(provider=provider)
    app.dependency_overrides[get_ingest_run_service] = lambda: service

    client = TestClient(app)
    response = client.get("/runs")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload[0]["id"] == "abc123"
    assert payload[0]["status"] == "completed"
    assert payload[0]["report"]["processed_count"] == 1
    assert payload[0]["report"]["invalid"][0]["reason"].startswith("Descriptor")

    app.dependency_overrides.clear()


def test_get_run_returns_404_for_missing_record(monkeypatch: MonkeyPatch) -> None:
    """Ensure /runs/{id} returns 404 for missing record."""
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

    provider = DummyIngestProvider([])
    service = IngestRunService(provider=provider)
    app.dependency_overrides[get_ingest_run_service] = lambda: service

    client = TestClient(app)
    response = client.get("/runs/not-here")

    assert response.status_code == 404, response.text

    app.dependency_overrides.clear()
