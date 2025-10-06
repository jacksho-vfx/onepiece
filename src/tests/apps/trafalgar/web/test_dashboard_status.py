"""Tests covering the Trafalgar dashboard status endpoint ingest summary."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Mapping

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web import dashboard


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
