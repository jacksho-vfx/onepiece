from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence, Type
from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web import dashboard


@pytest.mark.anyio("asyncio")
async def test_status_endpoint_aggregates_counts(
    dummy_shotgrid_client_cls: Type[Any],
    dummy_reconcile_provider_cls: Type[Any],
    dummy_ingest_facade_cls: Type[Any],
    dummy_render_facade_cls: Type[Any],
    dummy_review_facade_cls: Type[Any],
) -> None:
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
        lambda: dashboard.ShotGridService(dummy_shotgrid_client_cls(versions))
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: dashboard.ReconcileService(dummy_reconcile_provider_cls(reconcile_payload))
    )
    ingest_summary = {
        "counts": {"total": 3, "successful": 2, "failed": 0, "running": 1},
        "last_success_at": "2024-01-01T09:00:00+00:00",
        "failure_streak": 0,
    }
    ingest_facade = dummy_ingest_facade_cls(ingest_summary)
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: ingest_facade
    )
    render_summary = {
        "jobs": 4,
        "by_status": {"completed": 3, "running": 1},
        "by_farm": {"farm-a": 2, "farm-b": 2},
    }
    render_facade = dummy_render_facade_cls(render_summary)
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
    review_facade = dummy_review_facade_cls(review_summary)
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
    dummy_shotgrid_client_cls: Type[Any],
    dummy_reconcile_provider_cls: Type[Any],
    dummy_ingest_facade_cls: Type[Any],
    dummy_render_facade_cls: Type[Any],
    dummy_review_facade_cls: Type[Any],
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
        lambda: dashboard.ShotGridService(dummy_shotgrid_client_cls(versions))
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: dashboard.ReconcileService(dummy_reconcile_provider_cls(reconcile_payload))
    )
    ingest_facade = dummy_ingest_facade_cls(ingest_summary)
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: ingest_facade
    )
    render_facade = dummy_render_facade_cls(render_summary)
    dashboard.app.dependency_overrides[dashboard.get_render_dashboard_facade] = (
        lambda: render_facade
    )
    review_facade = dummy_review_facade_cls(review_summary)
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
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "admin-token")

    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
    ]

    service = dashboard.ShotGridService(
        dummy_shotgrid_client_cls(versions),
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
    dummy_shotgrid_client_cls: Type[Any],
    fake_monotonic_cls: Type[Any],
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "admin-token")

    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "alpha", "shot": "EP01_SC002_SH0010", "version": "v002"},
    ]

    client = dummy_shotgrid_client_cls(versions)
    clock = fake_monotonic_cls()

    service = dashboard.ShotGridService(
        client,
        known_projects={"alpha"},
        cache_ttl=60.0,
        cache_max_records=20,
        cache_max_projects=5,
        time_provider=clock,
    )
    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = lambda: service

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

    second = service.overall_status()
    assert second["versions"] == 2
    assert client.calls == 2


@pytest.mark.anyio("asyncio")
async def test_project_detail_returns_summary(
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    versions: list[dict[str, Any]] = [
        {
            "project": "ALPHA",
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
            "project": "Alpha",
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
        lambda: dashboard.ShotGridService(dummy_shotgrid_client_cls(versions))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/projects/AlPhA")

    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "AlPhA"
    assert data["episodes"] == 2
    assert data["shots"] == 2
    assert data["versions"] == 3
    assert data["approved_versions"] == 1
    assert data["status_totals"] == {"approved": 1, "published": 2}
    assert [item["version"] for item in data["latest_published"]] == ["v003", "v002"]


@pytest.mark.anyio("asyncio")
async def test_project_detail_missing_returns_404(
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: dashboard.ShotGridService(dummy_shotgrid_client_cls([]))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/projects/unknown")

    assert response.status_code == 404


@pytest.mark.anyio("asyncio")
async def test_errors_endpoint_uses_reconcile_provider(
    dummy_reconcile_provider_cls: Type[Any],
) -> None:
    payload = {
        "shotgrid": [{"shot": "a", "version": "v001"}],
        "filesystem": [{"shot": "a", "version": "v002"}],
        "s3": None,
    }

    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: dashboard.ReconcileService(dummy_reconcile_provider_cls(payload))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/errors")

    assert response.status_code == 200
    data = response.json()
    assert any(item["type"] in {"missing_in_fs", "version_mismatch"} for item in data)


@pytest.mark.anyio("asyncio")
async def test_error_summary_endpoint_groups_results(
    dummy_reconcile_provider_cls: Type[Any],
) -> None:
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
        lambda: dashboard.ReconcileService(dummy_reconcile_provider_cls(payload))
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
async def test_deliveries_endpoint_normalises_entries(
    dummy_delivery_provider_cls: Type[Any],
) -> None:
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
        lambda: dashboard.DeliveryService(dummy_delivery_provider_cls(deliveries))
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
async def test_deliveries_endpoint_handles_missing_entries(
    dummy_delivery_provider_cls: Type[Any],
) -> None:
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
        lambda: dashboard.DeliveryService(dummy_delivery_provider_cls(deliveries))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/deliveries/alpha")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["items"] == []
    assert data[0]["file_count"] == 0


@pytest.mark.anyio("asyncio")
async def test_deliveries_endpoint_uses_default_provider() -> None:
    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/deliveries/alpha")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio("asyncio")
async def test_deliveries_endpoint_includes_manifest_api_when_authorized(
    monkeypatch: pytest.MonkeyPatch,
    dummy_delivery_provider_cls: Type[Any],
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

    service = dashboard.DeliveryService(dummy_delivery_provider_cls(deliveries))
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
    dummy_delivery_provider_cls: Type[Any],
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

    service = dashboard.DeliveryService(dummy_delivery_provider_cls(deliveries))
    dashboard.app.dependency_overrides[dashboard.get_delivery_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/deliveries/alpha/delivery-4")

    assert response.status_code == 401


@pytest.mark.anyio("asyncio")
async def test_delivery_manifest_endpoint_returns_manifest(
    monkeypatch: pytest.MonkeyPatch,
    dummy_delivery_provider_cls: Type[Any],
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

    service = dashboard.DeliveryService(dummy_delivery_provider_cls(deliveries))
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
    dummy_delivery_provider_cls: Type[Any],
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "secret-token")

    service = dashboard.DeliveryService(dummy_delivery_provider_cls([]))
    dashboard.app.dependency_overrides[dashboard.get_delivery_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/deliveries/alpha/missing",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert response.status_code == 404


@pytest.mark.anyio("asyncio")
async def test_project_episode_endpoint_returns_grouped_stats(
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    versions = [
        {
            "project": "ALPHA",
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
            "project": "Alpha",
            "shot": "EP02_SC001_SH0100",
            "version": "v003",
            "status": "WIP",
        },
    ]

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: dashboard.ShotGridService(dummy_shotgrid_client_cls(versions))
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/projects/AlPhA/episodes")

    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "AlPhA"
    assert data["status_totals"] == {"approved": 1, "published": 1, "wip": 1}
    episodes = {entry["episode"]: entry for entry in data["episodes"]}
    assert episodes["EP01"]["versions"] == 2
    assert episodes["EP01"]["status_counts"] == {"approved": 1, "published": 1}
    assert episodes["EP02"]["shots"] == 1
