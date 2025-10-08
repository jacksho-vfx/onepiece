"""Tests covering the Trafalgar dashboard status endpoint ingest summary."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Mapping

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web import dashboard
from apps.uta.web import app as uta_app


class StubShotGridService:
    def overall_status(self) -> Mapping[str, int]:
        return {"projects": 1, "shots": 2, "versions": 3}


class StubReconcileService:
    def list_errors(self) -> list[dict[str, Any]]:
        return [{"type": "mismatch"}]


class StubIngestFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self.summary = summary
        self.calls: list[int] = []

    def summarise_recent_runs(self, limit: int = 10) -> Mapping[str, Any]:
        self.calls.append(limit)
        return self.summary


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    dashboard.app.dependency_overrides.clear()
    yield
    dashboard.app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_status_includes_ingest_summary_fields() -> None:
    ingest_summary = {
        "counts": {"total": 5, "successful": 4, "failed": 1, "running": 0},
        "last_success_at": "2024-02-01T12:00:00+00:00",
        "failure_streak": 2,
    }
    facade = StubIngestFacade(ingest_summary)

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: StubShotGridService()
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: StubReconcileService()
    )
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: facade
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingest"] == ingest_summary
    assert facade.calls == [10]
    assert payload["projects"] == 1
    assert payload["shots"] == 2
    assert payload["versions"] == 3
    assert payload["errors"] == 1


@pytest.mark.anyio("asyncio")
async def test_status_handles_partial_ingest_summary() -> None:
    ingest_summary: Mapping[str, Any] = {
        "counts": {"successful": "2", "failed": 1},
        "failure_streak": None,
    }
    facade = StubIngestFacade(ingest_summary)

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: StubShotGridService()
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: StubReconcileService()
    )
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: facade
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert "ingest" in payload
    assert payload["ingest"]["counts"] == {"successful": "2", "failed": 1}
    assert payload["ingest"].get("failure_streak") is None


@pytest.mark.anyio("asyncio")
async def test_dashboard_mount_injects_base_path(monkeypatch: pytest.MonkeyPatch) -> None:
    ingest_summary = {
        "counts": {"total": 1, "successful": 1, "failed": 0, "running": 0},
        "last_success_at": "2024-02-01T12:00:00+00:00",
        "failure_streak": 0,
    }
    facade = StubIngestFacade(ingest_summary)

    dashboard._TEMPLATE_CACHE = None
    monkeypatch.setattr(dashboard, "discover_projects", lambda: [])

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: StubShotGridService()
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: StubReconcileService()
    )
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: facade
    )

    transport = ASGITransport(app=uta_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        landing_page = await client.get("/")
        assert landing_page.status_code == 200
        assert 'data-dashboard-root="/dashboard/"' in landing_page.text

        dashboard_page = await client.get("/dashboard/")
        assert dashboard_page.status_code == 200
        iframe_html = dashboard_page.text
        assert 'data-base-path="/dashboard"' in iframe_html
        assert 'href="/dashboard/status"' in iframe_html
        assert "const target = joinPath(basePath, url);" in iframe_html

        status = await client.get("/dashboard/status")

    assert status.status_code == 200
    assert status.json()["ingest"] == ingest_summary
