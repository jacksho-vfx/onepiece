from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence, Protocol, Mapping, Generator

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web import dashboard


class DummyShotgridClient:
    def __init__(self, versions: Sequence[dict[str, Any]]) -> None:
        self._versions = list(versions)
        self.calls = 0

    def list_versions(self) -> Sequence[dict[str, Any]]:
        self.calls += 1
        return self._versions


class FakeMonotonic:
    def __init__(self) -> None:
        self._value = 0.0

    def advance(self, seconds: float) -> None:
        self._value += seconds

    def __call__(self) -> float:
        return self._value


class ReconcileDataProvider(Protocol):
    """Return reconciliation datasets used for mismatch detection."""

    def load(self) -> dict[str, Any]: ...


class DeliveryProvider(Protocol):
    """Provide delivery metadata for dashboard views."""

    def list_deliveries(self, project_name: str) -> Sequence[Mapping[str, Any]]: ...


class DummyReconcileProvider(ReconcileDataProvider):
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def load(self) -> dict[str, Any]:
        return self._payload


class DummyDeliveryProvider(DeliveryProvider):
    def __init__(self, deliveries: Sequence[dict[str, Any]]) -> None:
        self._deliveries = list(deliveries)

    def list_deliveries(self, project_name: str) -> Sequence[dict[str, Any]]:
        return [
            delivery
            for delivery in self._deliveries
            if delivery.get("project") == project_name
        ]


class DummyIngestFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self._summary = summary
        self.calls: list[int] = []

    def summarise_recent_runs(self, limit: int = 10) -> Mapping[str, Any]:
        self.calls.append(limit)
        return self._summary


@pytest.fixture(autouse=True)
def _clear_overrides() -> Generator[None, None, None]:
    dashboard.app.dependency_overrides.clear()
    dashboard.get_shotgrid_service.cache_clear()
    yield
    dashboard.app.dependency_overrides.clear()
    dashboard.get_shotgrid_service.cache_clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_shotgrid_service_caches_versions_until_ttl_expiry() -> None:
    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "alpha", "shot": "EP01_SC002_SH0010", "version": "v002"},
    ]
    client = DummyShotgridClient(versions)
    clock = FakeMonotonic()

    service = dashboard.ShotGridService(
        client,
        known_projects={"alpha"},
        cache_ttl=10.0,
        cache_max_records=10,
        time_provider=clock,
    )

    summary = service.overall_status()
    assert summary["versions"] == 2
    assert client.calls == 1

    project_summary = service.project_summary("alpha")
    assert project_summary["versions"] == 2
    assert client.calls == 1

    clock.advance(11.0)
    refreshed_summary = service.project_summary("alpha")
    assert refreshed_summary["versions"] == 2
    assert client.calls == 2


def test_shotgrid_service_skips_cache_when_dataset_exceeds_limit() -> None:
    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "alpha", "shot": "EP01_SC001_SH0020", "version": "v002"},
    ]
    client = DummyShotgridClient(versions)
    clock = FakeMonotonic()

    service = dashboard.ShotGridService(
        client,
        known_projects={"alpha"},
        cache_ttl=30.0,
        cache_max_records=1,
        time_provider=clock,
    )

    first = service.overall_status()
    assert first["versions"] == 2
    assert client.calls == 1

    second = service.overall_status()
    assert second["versions"] == 2
    assert client.calls == 2


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
    ingest_summary = {
        "counts": {"total": 3, "successful": 2, "failed": 0, "running": 1},
        "last_success_at": "2024-01-01T09:00:00+00:00",
        "failure_streak": 0,
    }
    ingest_facade = DummyIngestFacade(ingest_summary)
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: ingest_facade
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    data = response.json()
    assert data["projects"] == 2
    assert data["shots"] == 3
    assert data["versions"] == 3
    assert data["errors"] == 1
    assert data["ingest"] == ingest_summary
    assert ingest_facade.calls == [10]


@pytest.mark.anyio("asyncio")
async def test_project_detail_returns_summary() -> None:
    versions: list[dict[str, Any]] = [
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
    assert data["status_totals"] == {"apr": 1, "pub": 1, "published": 1}
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
async def test_error_summary_endpoint_groups_results() -> None:
    payload = {
        "shotgrid": [
            {"shot": "ep01", "version": "v001"},
            {"shot": "ep01", "version": "v002"},
        ],
        "filesystem": [
            {"shot": "ep01", "version": "v001", "path": "/tmp/a.mov"},
            {"shot": "ep01", "version": "v003", "path": "/tmp/a.mov"},
        ],
        "s3": None,
    }

    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: dashboard.ReconcileService(DummyReconcileProvider(payload))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/errors/summary")

    assert response.status_code == 200
    data = response.json()
    assert any(entry["type"] == "orphan_in_fs" for entry in data)
    match = next(entry for entry in data if entry["type"] == "orphan_in_fs")
    assert match["path"] == "/tmp/a.mov"
    assert match["count"] == 1
    assert match["shots"] == ["ep01"]


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
    assert data[0]["file_count"] == 2


@pytest.mark.anyio("asyncio")
async def test_project_episode_endpoint_returns_grouped_stats() -> None:
    versions = [
        {
            "project": "alpha",
            "episode": "EP01",
            "shot": "EP01_SC001_SH0010",
            "version": "v001",
            "status": "apr",
        },
        {
            "project": "alpha",
            "shot": "EP01_SC001_SH0010",
            "version": "v002",
            "status": "pub",
        },
        {
            "project": "alpha",
            "shot": "EP02_SC001_SH0100",
            "version": "v003",
            "status": "wip",
        },
    ]

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: dashboard.ShotGridService(DummyShotgridClient(versions))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/projects/alpha/episodes")

    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "alpha"
    assert data["status_totals"] == {"apr": 1, "pub": 1, "wip": 1}
    episodes = {entry["episode"]: entry for entry in data["episodes"]}
    assert episodes["EP01"]["versions"] == 2
    assert episodes["EP01"]["status_counts"] == {"apr": 1, "pub": 1}
    assert episodes["EP02"]["shots"] == 1


@pytest.mark.anyio("asyncio")
async def test_landing_page_returns_html() -> None:
    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "OnePiece Production Dashboard" in response.text
    assert 'href="/errors/summary"' in response.text
