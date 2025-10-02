from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web import dashboard


class DummyShotgridClient:
    def __init__(self, versions: Sequence[dict[str, Any]]) -> None:
        self._versions = list(versions)

    def list_versions(self) -> Sequence[dict[str, Any]]:
        return self._versions


class DummyReconcileProvider(dashboard.ReconcileDataProvider):
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def load(self) -> dict[str, Any]:
        return self._payload


class DummyDeliveryProvider(dashboard.DeliveryProvider):
    def __init__(self, deliveries: Sequence[dict[str, Any]]) -> None:
        self._deliveries = list(deliveries)

    def list_deliveries(self, project_name: str) -> Sequence[dict[str, Any]]:
        return [
            delivery
            for delivery in self._deliveries
            if delivery.get("project") == project_name
        ]


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    dashboard.app.dependency_overrides.clear()
    yield
    dashboard.app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_status_endpoint_aggregates_counts() -> None:
    versions = [
        {
            "project": "alpha",
            "shot": "EP01_SC001_SH0010",
            "version": "v001",
            "status": "apr",
        },
        {
            "project": "alpha",
            "shot": "EP02_SC003_SH0020",
            "version": "v002",
            "status": "pub",
        },
        {
            "project": "beta",
            "shot": "EP99_SC100_SH0500",
            "version": "v010",
            "status": "rev",
        },
    ]

    reconcile_payload = {
        "shotgrid": [{"shot": "ep01", "version": "v001"}],
        "filesystem": [],
        "s3": None,
    }

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: dashboard.ShotGridService(DummyShotgridClient(versions))
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: dashboard.ReconcileService(DummyReconcileProvider(reconcile_payload))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "projects": 2,
        "shots": 3,
        "versions": 3,
        "errors": 1,
    }


@pytest.mark.anyio("asyncio")
async def test_project_detail_returns_summary() -> None:
    versions = [
        {
            "project": "alpha",
            "shot": "EP01_SC001_SH0010",
            "version": "v001",
            "status": "apr",
            "user": "nami",
            "timestamp": datetime(2024, 1, 1, 9, 0, 0),
        },
        {
            "project": "alpha",
            "shot": "EP01_SC001_SH0010",
            "version": "v002",
            "status": "pub",
            "user": "zoro",
            "timestamp": "2024-01-01T10:00:00Z",
        },
        {
            "project": "alpha",
            "shot": "EP02_SC003_SH0020",
            "version": "v003",
            "status": "published",
            "user": "luffy",
            "timestamp": "2024-01-01T11:00:00+00:00",
        },
        {
            "project": "beta",
            "shot": "EP99_SC100_SH0500",
            "version": "v010",
            "status": "rev",
        },
    ]

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: dashboard.ShotGridService(DummyShotgridClient(versions))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/projects/alpha")

    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "alpha"
    assert data["episodes"] == 2
    assert data["shots"] == 2
    assert data["versions"] == 3
    assert data["approved_versions"] == 1
    assert [item["version"] for item in data["latest_published"]] == ["v003", "v002"]


@pytest.mark.anyio("asyncio")
async def test_project_detail_missing_returns_404() -> None:
    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: dashboard.ShotGridService(DummyShotgridClient([]))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/projects/unknown")

    assert response.status_code == 404


@pytest.mark.anyio("asyncio")
async def test_errors_endpoint_uses_reconcile_provider() -> None:
    payload = {
        "shotgrid": [{"shot": "a", "version": "v001"}],
        "filesystem": [{"shot": "a", "version": "v002"}],
        "s3": None,
    }

    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: dashboard.ReconcileService(DummyReconcileProvider(payload))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/errors")

    assert response.status_code == 200
    data = response.json()
    assert any(item["type"] in {"missing_in_fs", "version_mismatch"} for item in data)


@pytest.mark.anyio("asyncio")
async def test_deliveries_endpoint_normalises_entries() -> None:
    deliveries = [
        {
            "project": "alpha",
            "name": "alpha_20240101",
            "archive": "/tmp/alpha.zip",
            "manifest": "/tmp/alpha.json",
            "created_at": "2024-01-01T10:00:00Z",
            "entries": [
                {
                    "show": "Alpha",
                    "episode": "EP01",
                    "scene": "SC001",
                    "shot": "SH0010",
                    "asset": "comp",
                    "version": 1,
                    "source_path": "/tmp/source.mov",
                    "delivery_path": "media/clip.mov",
                    "checksum": "abc",
                },
                {
                    "show": "Alpha",
                    "episode": "EP01",
                    "scene": "SC001",
                    "shot": "SH0020",
                    "asset": "comp",
                    "version": 2,
                    "source_path": "/tmp/source2.mov",
                    "delivery_path": "media/clip2.mov",
                    "checksum": "def",
                },
            ],
        }
    ]

    dashboard.app.dependency_overrides[dashboard.get_delivery_service] = (
        lambda: dashboard.DeliveryService(DummyDeliveryProvider(deliveries))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/deliveries/alpha")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["name"] == "alpha_20240101"
    assert data[0]["created_at"].startswith("2024-01-01")
    assert len(data[0]["items"]) == 2


@pytest.mark.anyio("asyncio")
async def test_landing_page_returns_html() -> None:
    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "OnePiece Production Dashboard" in response.text
    assert "href=\"/status\"" in response.text
