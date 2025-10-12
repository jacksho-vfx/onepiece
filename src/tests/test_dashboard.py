from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Mapping, Sequence
from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.providers import (
    DeliveryProvider,
    ProviderMetadata,
    ReconcileDataProvider,
)
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


class DummyReconcileProvider(ReconcileDataProvider):
    metadata = ProviderMetadata(
        name="test-reconcile",
        version="1.0",
        data_schema={},
        capabilities=("testing",),
    )

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def load(self) -> dict[str, Any]:
        return self._payload


class DummyDeliveryProvider(DeliveryProvider):
    metadata = ProviderMetadata(
        name="test-delivery",
        version="1.0",
        data_schema={},
        capabilities=("testing",),
    )

    def __init__(self, deliveries: Sequence[dict[str, Any]]) -> None:
        self._deliveries = list(deliveries)

    def list_deliveries(self, project_name: str) -> Sequence[dict[str, Any]]:
        return [
            delivery
            for delivery in self._deliveries
            if delivery.get("project") == project_name
        ]


class SequencedDeliveryProvider(DeliveryProvider):
    metadata = ProviderMetadata(
        name="sequenced-delivery",
        version="1.0",
        data_schema={},
        capabilities=("testing",),
    )

    def __init__(self, responses: Sequence[Sequence[Mapping[str, Any]]]) -> None:
        self._responses = [list(response) for response in responses]
        self.requests: list[str] = []

    def list_deliveries(self, project_name: str) -> Sequence[Mapping[str, Any]]:
        self.requests.append(project_name)
        if self._responses:
            response = self._responses.pop(0)
        else:
            response = []
        return [copy.deepcopy(item) for item in response]


class DummyIngestFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self._summary = summary
        self.calls: list[int] = []

    def summarise_recent_runs(self, limit: int = 10) -> Mapping[str, Any]:
        self.calls.append(limit)
        return self._summary


class DummyRenderFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self._summary = summary
        self.calls: int = 0

    def summarise_jobs(self) -> Mapping[str, Any]:
        self.calls += 1
        return self._summary


class DummyReviewFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self._summary = summary
        self.project_calls: list[list[str]] = []

    def summarise_projects(self, project_names: Iterable[str]) -> Mapping[str, Any]:
        self.project_calls.append(list(project_names))
        return self._summary


def test_shotgrid_service_discovers_projects_and_updates_registry(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path = tmp_path / "projects.json"
    monkeypatch.setenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY", str(registry_path))
    monkeypatch.delenv("ONEPIECE_DASHBOARD_PROJECTS", raising=False)

    versions: Sequence[dict[str, Any]] = [
        {"project": "alpha"},
        {"project": {"name": "beta"}},
        {"project": {"code": "alpha"}},
    ]

    client = DummyShotgridClient(versions)
    service = dashboard.ShotGridService(client, known_projects={"omega"})

    projects = service.discover_projects()

    assert projects == ["alpha", "beta", "omega"]
    stored = json.loads(registry_path.read_text(encoding="utf-8"))
    assert stored == projects


def test_shotgrid_service_discover_projects_falls_back_to_cache_and_env(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path = tmp_path / "projects.json"
    registry_path.write_text(json.dumps(["cached"]), encoding="utf-8")
    monkeypatch.setenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY", str(registry_path))

    class OfflineShotgridClient(DummyShotgridClient):
        def list_versions(self) -> Sequence[dict[str, Any]]:
            raise RuntimeError("offline")

    service = dashboard.ShotGridService(
        OfflineShotgridClient([]),
        known_projects={"env_project"},
    )

    projects = service.discover_projects()

    assert projects == ["cached", "env_project"]


def test_shotgrid_service_uses_discovered_projects_without_reinit(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
) -> None:
    class ProjectFetchingClient:
        def __init__(self) -> None:
            self.version_requests: list[str] = []

        def list_projects(self) -> Sequence[Mapping[str, Any]]:
            return [{"name": "gamma"}]

        def get_versions_for_project(
            self, project_name: str
        ) -> Sequence[Mapping[str, Any]]:
            self.version_requests.append(project_name)
            if project_name == "alpha":
                return [
                    {
                        "project": "alpha",
                        "shot": "EP01_SC001_SH0010",
                        "status": "Approved",
                    }
                ]
            if project_name == "gamma":
                return [
                    {
                        "project": "gamma",
                        "shot": "EP01_SC001_SH0020",
                        "status": "Published",
                    }
                ]
            return []

    registry_path = tmp_path / "projects.json"
    monkeypatch.setenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY", str(registry_path))

    client = ProjectFetchingClient()
    service = dashboard.ShotGridService(client, known_projects={"alpha"})

    projects = service.discover_projects()

    assert projects == ["alpha", "gamma"]

    summary = service.project_summary("gamma")

    assert summary["project"] == "gamma"
    assert summary["versions"] == 1
    assert "gamma" in client.version_requests


def test_shotgrid_service_injects_project_name_for_fetched_versions() -> None:
    class ProjectFetchingClient:
        def __init__(self) -> None:
            self.requests: list[str] = []

        def get_versions_for_project(
            self, project_name: str
        ) -> Sequence[Mapping[str, Any]]:
            self.requests.append(project_name)
            if project_name == "alpha":
                return [
                    {
                        "shot": "EP01_SC001_SH0010",
                        "version": "v001",
                        "status": "Published",
                    }
                ]
            return []

    client = ProjectFetchingClient()
    service = dashboard.ShotGridService(client, known_projects={"alpha"})

    summary = service.project_summary("alpha")

    assert summary["versions"] == 1
    assert client.requests == ["alpha"]


@pytest.fixture(autouse=True)
def _clear_overrides() -> Generator[None, None, None]:
    dashboard.app.dependency_overrides.clear()
    dashboard.get_shotgrid_service.cache_clear()
    for attr in (
        "dashboard_cache_ttl",
        "dashboard_cache_max_records",
        "dashboard_cache_max_projects",
    ):
        if hasattr(dashboard.app.state, attr):
            delattr(dashboard.app.state, attr)
    yield
    dashboard.app.dependency_overrides.clear()
    dashboard.get_shotgrid_service.cache_clear()
    for attr in (
        "dashboard_cache_ttl",
        "dashboard_cache_max_records",
        "dashboard_cache_max_projects",
    ):
        if hasattr(dashboard.app.state, attr):
            delattr(dashboard.app.state, attr)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def delivery_provider_factory() -> Callable[..., SequencedDeliveryProvider]:
    def factory(*responses: Sequence[Mapping[str, Any]]) -> SequencedDeliveryProvider:
        return SequencedDeliveryProvider(responses)

    return factory


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


def test_shotgrid_service_skips_cache_when_project_count_exceeds_limit() -> None:
    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "beta", "shot": "EP01_SC002_SH0010", "version": "v002"},
    ]
    client = DummyShotgridClient(versions)
    clock = FakeMonotonic()

    service = dashboard.ShotGridService(
        client,
        known_projects={"alpha", "beta"},
        cache_ttl=30.0,
        cache_max_records=10,
        cache_max_projects=1,
        time_provider=clock,
    )

    first = service.overall_status()
    assert first["versions"] == 2
    assert client.calls == 1

    second = service.overall_status()
    assert second["versions"] == 2
    assert client.calls == 2


def test_shotgrid_service_manual_invalidation_clears_cache() -> None:
    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "alpha", "shot": "EP01_SC002_SH0010", "version": "v002"},
    ]
    client = DummyShotgridClient(versions)
    clock = FakeMonotonic()

    service = dashboard.ShotGridService(
        client,
        known_projects={"alpha"},
        cache_ttl=60.0,
        cache_max_records=10,
        cache_max_projects=10,
        time_provider=clock,
    )

    first = service.overall_status()
    assert first["versions"] == 2
    assert client.calls == 1

    service.invalidate_cache()

    second = service.overall_status()
    assert second["versions"] == 2
    assert client.calls == 2


def test_shotgrid_service_overall_status_handles_mapping_projects() -> None:
    versions: Sequence[dict[str, Any]] = [
        {"project": {"name": "alpha"}},
        {"project": {"name": {"value": "beta"}}},
        {"project": "alpha"},
    ]

    service = dashboard.ShotGridService(DummyShotgridClient(versions))

    summary = service.overall_status()

    assert summary["projects"] == 2


@pytest.mark.anyio("asyncio")
async def test_landing_page_uses_discovered_projects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry_path = tmp_path / "projects.json"
    monkeypatch.setenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY", str(registry_path))
    monkeypatch.delenv("ONEPIECE_DASHBOARD_PROJECTS", raising=False)

    versions = [
        {"project": "beta"},
        {"project": "alpha"},
    ]

    service = dashboard.ShotGridService(DummyShotgridClient(versions))
    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    text = response.text
    assert "Summary for alpha" in text
    assert "Episode breakdown for alpha" in text
    assert "[&quot;alpha&quot;, &quot;beta&quot;]" in text


@pytest.mark.anyio("asyncio")
async def test_status_endpoint_aggregates_counts() -> None:
    versions: Sequence[dict[str, Any]] = [
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
            "project": {"name": {"value": "beta"}},
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
    render_summary = {
        "jobs": 4,
        "by_status": {"completed": 3, "running": 1},
        "by_farm": {"farm-a": 2, "farm-b": 2},
    }
    render_facade = DummyRenderFacade(render_summary)
    dashboard.app.dependency_overrides[dashboard.get_render_dashboard_facade] = (
        lambda: render_facade
    )
    review_summary = {
        "totals": {
            "projects": 2,
            "playlists": 3,
            "clips": 10,
            "shots": 6,
            "duration_seconds": 150.0,
        },
        "projects": [
            {
                "project": "alpha",
                "playlists": 2,
                "clips": 6,
                "shots": 4,
                "duration_seconds": 120.0,
            },
            {
                "project": "beta",
                "playlists": 1,
                "clips": 4,
                "shots": 2,
                "duration_seconds": 30.0,
            },
        ],
    }
    review_facade = DummyReviewFacade(review_summary)
    dashboard.app.dependency_overrides[dashboard.get_review_dashboard_facade] = (
        lambda: review_facade
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
    assert data["render"] == render_summary
    assert render_facade.calls == 1
    assert data["review"] == review_summary
    assert review_facade.project_calls
    assert set(review_facade.project_calls[0]).issuperset({"alpha", "beta"})


@pytest.mark.anyio("asyncio")
async def test_metrics_endpoint_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")

    assert response.status_code == 503

    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "secret-token")

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")

    assert response.status_code == 401


@pytest.mark.anyio("asyncio")
async def test_metrics_endpoint_combines_dashboards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "very-secret")

    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "beta", "shot": "EP02_SC100_SH0500", "version": "v010"},
        {"project": "alpha", "shot": "EP01_SC002_SH0020", "version": "v002"},
    ]
    reconcile_payload = {
        "shotgrid": [{"shot": "ep01", "version": "v001"}],
        "filesystem": [],
        "s3": None,
    }
    ingest_summary = {
        "counts": {"total": 4, "successful": 3, "failed": 1, "running": 0},
        "last_success_at": "2024-01-01T09:00:00+00:00",
        "failure_streak": 0,
    }
    render_summary = {
        "jobs": 5,
        "by_status": {"completed": 3, "running": 1, "failed": 1},
        "by_farm": {"mock": 4, "tractor": 1},
    }
    review_summary = {
        "totals": {
            "projects": 2,
            "playlists": 3,
            "clips": 12,
            "shots": 7,
            "duration_seconds": 180.0,
        },
        "projects": [
            {
                "project": "alpha",
                "playlists": 2,
                "clips": 9,
                "shots": 5,
                "duration_seconds": 120.0,
            },
            {
                "project": "beta",
                "playlists": 1,
                "clips": 3,
                "shots": 2,
                "duration_seconds": 60.0,
            },
        ],
    }

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: dashboard.ShotGridService(DummyShotgridClient(versions))
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: dashboard.ReconcileService(DummyReconcileProvider(reconcile_payload))
    )
    ingest_facade = DummyIngestFacade(ingest_summary)
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: ingest_facade
    )
    render_facade = DummyRenderFacade(render_summary)
    dashboard.app.dependency_overrides[dashboard.get_render_dashboard_facade] = (
        lambda: render_facade
    )
    review_facade = DummyReviewFacade(review_summary)
    dashboard.app.dependency_overrides[dashboard.get_review_dashboard_facade] = (
        lambda: review_facade
    )

    headers = {"Authorization": "Bearer very-secret"}
    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics", headers=headers)

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == {
        "projects": 2,
        "shots": 3,
        "versions": 3,
        "errors": 1,
    }
    assert payload["ingest"]["counts"] == ingest_summary["counts"]
    assert payload["ingest"]["last_success_at"] == "2024-01-01T09:00:00+00:00"
    assert payload["render"] == {
        "jobs": 5,
        "by_status": {"completed": 3, "failed": 1, "running": 1},
        "by_farm": {"mock": 4, "tractor": 1},
    }
    assert payload["review"]["totals"]["playlists"] == 3
    assert payload["review"]["projects"][0]["project"] in {"alpha", "beta"}
    assert render_facade.calls == 1
    assert review_facade.project_calls
    assert set(review_facade.project_calls[0]).issuperset({"alpha", "beta"})


@pytest.mark.anyio("asyncio")
async def test_admin_cache_endpoint_returns_active_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "admin-token")

    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
    ]

    service = dashboard.ShotGridService(
        DummyShotgridClient(versions),
        cache_ttl=45.0,
        cache_max_records=123,
        cache_max_projects=7,
    )
    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    headers = {"Authorization": "Bearer admin-token"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin/cache", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ttl_seconds"] == pytest.approx(45.0)
    assert payload["max_records"] == 123
    assert payload["max_projects"] == 7


@pytest.mark.anyio("asyncio")
async def test_admin_cache_endpoint_updates_settings_and_flushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "admin-token")

    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "alpha", "shot": "EP01_SC002_SH0010", "version": "v002"},
    ]

    client = DummyShotgridClient(versions)
    clock = FakeMonotonic()

    service = dashboard.ShotGridService(
        client,
        known_projects={"alpha"},
        cache_ttl=60.0,
        cache_max_records=20,
        cache_max_projects=5,
        time_provider=clock,
    )
    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = lambda: service

    # Prime the cache to ensure the flush path clears it.
    first = service.overall_status()
    assert first["versions"] == 2
    assert client.calls == 1

    transport = ASGITransport(app=dashboard.app)
    headers = {"Authorization": "Bearer admin-token"}
    payload = {
        "ttl_seconds": 5.5,
        "max_records": 2,
        "max_projects": 1,
        "flush": True,
    }
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        response = await http_client.post("/admin/cache", json=payload, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ttl_seconds"] == pytest.approx(5.5)
    assert payload["max_records"] == 2
    assert payload["max_projects"] == 1

    assert getattr(dashboard.app.state, "dashboard_cache_ttl") == pytest.approx(5.5)
    assert getattr(dashboard.app.state, "dashboard_cache_max_records") == 2
    assert getattr(dashboard.app.state, "dashboard_cache_max_projects") == 1

    # Cache was flushed, so the next call should hit ShotGrid again.
    second = service.overall_status()
    assert second["versions"] == 2
    assert client.calls == 2


@pytest.mark.anyio("asyncio")
async def test_project_detail_returns_summary() -> None:
    versions: list[dict[str, Any]] = [
        {
            "project": "alpha",
            "shot": "EP01_SC001_SH0010",
            "version": "v001",
            "status": "APR",
            "user": "nami",
            "timestamp": datetime(2024, 1, 1, 9, 0, 0),
        },
        {
            "project": "alpha",
            "shot": "EP01_SC001_SH0010",
            "version": "v002",
            "status": "Final",
            "user": "zoro",
            "timestamp": "2024-01-01T10:00:00Z",
        },
        {
            "project": "alpha",
            "shot": "EP02_SC003_SH0020",
            "version": "v003",
            "status": "Published",
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
    assert data["status_totals"] == {"approved": 1, "published": 2}
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
async def test_deliveries_endpoint_handles_missing_entries() -> None:
    deliveries = [
        {
            "project": "alpha",
            "name": "alpha_20240101",
            "archive": "/tmp/alpha.zip",
            "manifest": "/tmp/alpha.json",
            "created_at": "2024-01-01T10:00:00Z",
            "entries": None,
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
    assert data[0]["items"] == []
    assert data[0]["file_count"] == 0


@pytest.mark.anyio("asyncio")
async def test_deliveries_endpoint_includes_manifest_api_when_authorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "secret-token")

    deliveries = [
        {
            "project": "alpha",
            "id": "delivery-3",
            "manifest": "/tmp/alpha_manifest.json",
            "entries": [],
        }
    ]

    service = dashboard.DeliveryService(DummyDeliveryProvider(deliveries))
    dashboard.app.dependency_overrides[dashboard.get_delivery_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/deliveries/alpha",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data[0]["delivery_id"] == "delivery-3"
    assert data[0]["manifest_api"].endswith("/deliveries/alpha/delivery-3")


@pytest.mark.anyio("asyncio")
async def test_delivery_manifest_endpoint_requires_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "secret-token")

    deliveries = [
        {
            "project": "alpha",
            "id": "delivery-4",
            "manifest": "/tmp/alpha.json",
            "entries": [],
        }
    ]

    service = dashboard.DeliveryService(DummyDeliveryProvider(deliveries))
    dashboard.app.dependency_overrides[dashboard.get_delivery_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/deliveries/alpha/delivery-4")

    assert response.status_code == 401


@pytest.mark.anyio("asyncio")
async def test_delivery_manifest_endpoint_returns_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "secret-token")

    deliveries = [
        {
            "project": "alpha",
            "id": "delivery-5",
            "manifest": "/tmp/alpha.json",
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
                }
            ],
        }
    ]

    service = dashboard.DeliveryService(DummyDeliveryProvider(deliveries))
    dashboard.app.dependency_overrides[dashboard.get_delivery_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    encoded_identifier = quote("/tmp/alpha.json", safe="")
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            f"/deliveries/alpha/{encoded_identifier}",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["files"][0]["delivery_path"] == "media/clip.mov"


@pytest.mark.anyio("asyncio")
async def test_delivery_manifest_endpoint_returns_404_for_missing_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "secret-token")

    service = dashboard.DeliveryService(DummyDeliveryProvider([]))
    dashboard.app.dependency_overrides[dashboard.get_delivery_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/deliveries/alpha/missing",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert response.status_code == 404


def test_delivery_service_prefers_provider_manifest_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[Mapping[str, Any]]] = []

    def fake_get_manifest_data(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        calls.append(list(entries))
        return {"files": []}

    monkeypatch.setattr(dashboard, "get_manifest_data", fake_get_manifest_data)

    manifest_items = [
        {
            "show": "Alpha",
            "episode": "EP01",
            "scene": "SC001",
            "shot": "SH0010",
            "asset": "comp",
            "version": 1,
            "source_path": "/tmp/source.mov",
            "delivery_path": "media/clip.mov",
            "checksum": "cached",
        }
    ]

    deliveries = [
        {
            "project": "alpha",
            "id": "delivery-1",
            "name": "alpha_20240101",
            "archive": "/tmp/alpha.zip",
            "manifest": "/tmp/alpha.json",
            "manifest_data": {"files": manifest_items},
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
                }
            ],
        }
    ]

    service = dashboard.DeliveryService(DummyDeliveryProvider(deliveries))
    payload = service.list_deliveries("alpha")

    assert payload[0]["items"] == manifest_items
    assert payload[0]["file_count"] == 1
    assert calls == []


def test_delivery_service_caches_recomputed_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[Mapping[str, Any]]] = []

    def fake_get_manifest_data(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        calls.append(list(entries))
        return {
            "files": [
                {
                    "show": "Alpha",
                    "episode": "EP01",
                    "scene": "SC001",
                    "shot": "SH0010",
                    "asset": "comp",
                    "version": 1,
                    "source_path": "/tmp/source.mov",
                    "delivery_path": "media/clip.mov",
                    "checksum": "generated",
                }
            ]
        }

    monkeypatch.setattr(dashboard, "get_manifest_data", fake_get_manifest_data)

    deliveries = [
        {
            "project": "alpha",
            "id": "delivery-2",
            "name": "alpha_20240102",
            "archive": "/tmp/alpha_02.zip",
            "manifest": "/tmp/alpha_02.json",
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
                }
            ],
        }
    ]

    service = dashboard.DeliveryService(DummyDeliveryProvider(deliveries))

    first = service.list_deliveries("alpha")
    second = service.list_deliveries("alpha")

    assert len(calls) == 1
    assert first == second
    assert first[0]["file_count"] == 1


def test_delivery_service_get_manifest_supports_multiple_identifiers() -> None:
    deliveries = [
        {
            "project": "alpha",
            "id": "delivery-2",
            "manifest": "/tmp/alpha.json",
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
                }
            ],
        }
    ]

    service = dashboard.DeliveryService(DummyDeliveryProvider(deliveries))

    manifest = service.get_delivery_manifest("alpha", "/tmp/alpha.json")
    assert manifest["files"][0]["delivery_path"] == "media/clip.mov"

    manifest["files"].append({"delivery_path": "mutated.mov"})
    manifest["files"][0]["delivery_path"] = "tampered.mov"

    cached = service.get_delivery_manifest("alpha", "delivery-2")
    assert cached["files"][0]["delivery_path"] == "media/clip.mov"
    assert cached["files"][0] is not manifest["files"][0]


def test_delivery_service_get_manifest_raises_for_unknown_delivery() -> None:
    service = dashboard.DeliveryService(DummyDeliveryProvider([]))

    with pytest.raises(KeyError):
        service.get_delivery_manifest("alpha", "missing")


def test_delivery_service_reuses_cached_manifest_and_returns_deep_copy(
    delivery_provider_factory: Callable[..., SequencedDeliveryProvider],
) -> None:
    provider = delivery_provider_factory(
        [
            {
                "project": "alpha",
                "id": "delivery-1",
                "manifest_data": {"files": [{"path": "alpha.mov"}]},
            }
        ],
        [
            {
                "project": "alpha",
                "id": "delivery-1",
            }
        ],
    )
    service = dashboard.DeliveryService(
        provider,
        manifest_cache_size=4,
    )

    first = service.list_deliveries("alpha")
    assert first[0]["items"] == [{"path": "alpha.mov"}]

    original_items = first[0]["items"]
    original_file = original_items[0]
    original_items.append({"path": "mutated.mov"})
    original_file["path"] = "tampered.mov"

    second = service.list_deliveries("alpha")

    assert second[0]["items"] == [{"path": "alpha.mov"}]
    assert second[0]["items"] is not original_items
    assert second[0]["items"][0] is not original_file


def test_delivery_service_evicts_oldest_manifest_when_cache_full(
    delivery_provider_factory: Callable[..., SequencedDeliveryProvider],
) -> None:
    provider = delivery_provider_factory(
        [
            {
                "project": "alpha",
                "id": "delivery-1",
                "manifest_data": {"files": [{"path": "alpha.mov"}]},
            }
        ],
        [
            {
                "project": "alpha",
                "id": "delivery-2",
                "manifest_data": {"files": [{"path": "bravo.mov"}]},
            }
        ],
        [
            {
                "project": "alpha",
                "id": "delivery-1",
            }
        ],
    )

    service = dashboard.DeliveryService(
        provider,
        manifest_cache_size=1,
    )

    first = service.list_deliveries("alpha")
    assert first[0]["items"] == [{"path": "alpha.mov"}]
    assert list(service._manifest_cache.keys()) == ["delivery-1"]

    second = service.list_deliveries("alpha")
    assert second[0]["items"] == [{"path": "bravo.mov"}]
    assert list(service._manifest_cache.keys()) == ["delivery-2"]

    third = service.list_deliveries("alpha")
    assert third[0]["items"] == []
    assert list(service._manifest_cache.keys()) == ["delivery-1"]


def test_delivery_service_disables_manifest_cache_when_size_zero(
    delivery_provider_factory: Callable[..., SequencedDeliveryProvider],
) -> None:
    provider = delivery_provider_factory(
        [
            {
                "project": "alpha",
                "id": "delivery-1",
                "manifest_data": {"files": [{"path": "alpha.mov"}]},
            }
        ],
        [
            {
                "project": "alpha",
                "id": "delivery-1",
            }
        ],
    )

    service = dashboard.DeliveryService(
        provider,
        manifest_cache_size=0,
    )

    first = service.list_deliveries("alpha")
    assert first[0]["items"] == [{"path": "alpha.mov"}]
    assert list(service._manifest_cache.keys()) == []

    second = service.list_deliveries("alpha")
    assert second[0]["items"] == []
    assert list(service._manifest_cache.keys()) == []


@pytest.mark.anyio("asyncio")
async def test_project_episode_endpoint_returns_grouped_stats() -> None:
    versions = [
        {
            "project": "alpha",
            "episode": "EP01",
            "shot": "EP01_SC001_SH0010",
            "version": "v001",
            "status": "Approved",
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
            "status": "WIP",
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
    assert data["status_totals"] == {"approved": 1, "published": 1, "wip": 1}
    episodes = {entry["episode"]: entry for entry in data["episodes"]}
    assert episodes["EP01"]["versions"] == 2
    assert episodes["EP01"]["status_counts"] == {"approved": 1, "published": 1}
    assert episodes["EP02"]["shots"] == 1


@pytest.mark.anyio("asyncio")
async def test_landing_page_returns_html() -> None:
    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "OnePiece Production Dashboard" in response.text
    assert 'href="/errors/summary"' in response.text
