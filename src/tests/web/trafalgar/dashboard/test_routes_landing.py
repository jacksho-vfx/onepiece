from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence, Type

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web import dashboard


@pytest.mark.anyio("asyncio")
async def test_landing_page_returns_html() -> None:
    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "OnePiece Production Dashboard" in response.text
    assert 'href="/errors/summary"' in response.text


@pytest.mark.anyio("asyncio")
async def test_landing_page_uses_discovered_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    registry_path = tmp_path / "projects.json"
    monkeypatch.setenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY", str(registry_path))
    monkeypatch.delenv("ONEPIECE_DASHBOARD_PROJECTS", raising=False)

    versions: Sequence[dict[str, Any]] = [
        {"project": "beta"},
        {"project": "alpha"},
    ]

    service = dashboard.ShotGridService(dummy_shotgrid_client_cls(versions))
    dashboard.app.dependency_overrides[dashboard.get_shotgrid_service] = lambda: service

    transport = ASGITransport(app=dashboard.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    text = response.text
    assert "Summary for alpha" in text
    assert "Episode breakdown for alpha" in text
    assert "[&quot;alpha&quot;, &quot;beta&quot;]" in text
