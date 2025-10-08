"""Tests covering the Trafalgar dashboard status endpoint ingest summary."""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Mapping

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web import dashboard


class StubShotGridService:
    def overall_status(self) -> Mapping[str, int]:
        return {"projects": 1, "shots": 2, "versions": 3}

    def discover_projects(self) -> list[str]:
        return ["alpha"]


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


class StubRenderFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self.summary = summary
        self.calls = 0

    def summarise_jobs(self) -> Mapping[str, Any]:
        self.calls += 1
        return self.summary


class StubReviewFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self.summary = summary
        self.project_calls: list[list[str]] = []

    def summarise_projects(self, project_names: Iterable[str]) -> Mapping[str, Any]:
        self.project_calls.append(list(project_names))
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
    render_summary = {
        "jobs": 3,
        "by_status": {"completed": 2, "running": 1},
        "by_farm": {"mock": 3},
    }
    render_facade = StubRenderFacade(render_summary)
    review_summary = {
        "totals": {
            "projects": 1,
            "playlists": 2,
            "clips": 4,
            "shots": 3,
            "duration_seconds": 120.0,
        },
        "projects": [
            {
                "project": "alpha",
                "playlists": 2,
                "clips": 4,
                "shots": 3,
                "duration_seconds": 120.0,
            }
        ],
    }
    review_facade = StubReviewFacade(review_summary)

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: StubShotGridService()
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: StubReconcileService()
    )
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: facade
    )
    dashboard.app.dependency_overrides[dashboard.get_render_dashboard_facade] = (
        lambda: render_facade
    )
    dashboard.app.dependency_overrides[dashboard.get_review_dashboard_facade] = (
        lambda: review_facade
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingest"] == ingest_summary
    assert payload["render"] == render_summary
    assert payload["review"] == review_summary
    assert facade.calls == [10]
    assert render_facade.calls == 1
    assert review_facade.project_calls == [["alpha"]]
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
    render_summary = {"jobs": None, "by_status": {"running": "1"}}
    render_facade = StubRenderFacade(render_summary)
    review_summary: Mapping[str, Any] = {"totals": {"playlists": "3"}, "projects": []}
    review_facade = StubReviewFacade(review_summary)

    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = (
        lambda: StubShotGridService()
    )
    dashboard.app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: StubReconcileService()
    )
    dashboard.app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: facade
    )
    dashboard.app.dependency_overrides[dashboard.get_render_dashboard_facade] = (
        lambda: render_facade
    )
    dashboard.app.dependency_overrides[dashboard.get_review_dashboard_facade] = (
        lambda: review_facade
    )

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert "ingest" in payload
    assert payload["ingest"]["counts"] == {"successful": "2", "failed": 1}
    assert payload["ingest"].get("failure_streak") is None
    assert payload["render"] == {
        "jobs": 0,
        "by_status": {"running": 1},
        "by_farm": {},
    }
    assert payload["review"] == {
        "totals": {
            "projects": 0,
            "playlists": 3,
            "clips": 0,
            "shots": 0,
            "duration_seconds": 0.0,
        },
        "projects": [],
    }
