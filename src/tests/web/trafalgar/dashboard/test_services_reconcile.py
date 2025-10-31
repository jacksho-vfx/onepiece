from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Iterable, Mapping, Type

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from apps.trafalgar.web import dashboard


@pytest.mark.anyio("asyncio")
async def test_render_dashboard_facade_offloads_job_listing() -> None:
    class SlowService:
        def list_jobs(self) -> list[Any]:
            time.sleep(0.2)
            return []

    facade = dashboard.RenderDashboardFacade(service=SlowService())

    marker = asyncio.Event()

    async def _mark() -> None:
        await asyncio.sleep(0.01)
        marker.set()

    setter_task = asyncio.create_task(_mark())
    wait_task = asyncio.create_task(asyncio.wait_for(marker.wait(), timeout=0.1))

    summary = await asyncio.wait_for(facade.summarise_jobs(), timeout=1)

    await wait_task
    await setter_task

    assert marker.is_set()
    assert summary == {"jobs": 0, "by_status": {}, "by_farm": {}}


def test_reconcile_service_uses_default_provider() -> None:
    service = dashboard.ReconcileService()

    assert service.list_errors() == []
    assert service.summarise_errors() == []


def test_delivery_service_uses_default_provider() -> None:
    service = dashboard.DeliveryService()

    payload = service.list_deliveries("alpha")

    assert payload == []


def test_require_dashboard_auth_accepts_matching_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "super-secret")

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="super-secret")

    dashboard.require_dashboard_auth(credentials)


def test_require_dashboard_auth_rejects_mismatched_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "super-secret")

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="nope")

    with pytest.raises(HTTPException) as excinfo:
        dashboard.require_dashboard_auth(credentials)

    assert excinfo.value.status_code == 401


def test_delivery_service_prefers_provider_manifest_data(
    monkeypatch: pytest.MonkeyPatch,
    dummy_delivery_provider_cls: Type[Any],
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

    service = dashboard.DeliveryService(dummy_delivery_provider_cls(deliveries))
    payload = service.list_deliveries("alpha")

    assert payload[0]["items"] == manifest_items
    assert payload[0]["file_count"] == 1
    assert calls == []


def test_delivery_service_caches_recomputed_manifest(
    monkeypatch: pytest.MonkeyPatch,
    dummy_delivery_provider_cls: Type[Any],
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

    service = dashboard.DeliveryService(dummy_delivery_provider_cls(deliveries))

    first = service.list_deliveries("alpha")
    second = service.list_deliveries("alpha")

    assert len(calls) == 1
    assert first == second
    assert first[0]["file_count"] == 1


def test_delivery_service_get_manifest_supports_multiple_identifiers(
    dummy_delivery_provider_cls: Type[Any],
) -> None:
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

    service = dashboard.DeliveryService(dummy_delivery_provider_cls(deliveries))

    manifest = service.get_delivery_manifest("alpha", "/tmp/alpha.json")
    assert manifest["files"][0]["delivery_path"] == "media/clip.mov"

    manifest["files"].append({"delivery_path": "mutated.mov"})
    manifest["files"][0]["delivery_path"] = "tampered.mov"

    cached = service.get_delivery_manifest("alpha", "delivery-2")
    assert cached["files"][0]["delivery_path"] == "media/clip.mov"
    assert cached["files"][0] is not manifest["files"][0]


def test_delivery_service_get_manifest_raises_for_unknown_delivery(
    dummy_delivery_provider_cls: Type[Any],
) -> None:
    service = dashboard.DeliveryService(dummy_delivery_provider_cls([]))

    with pytest.raises(KeyError):
        service.get_delivery_manifest("alpha", "missing")


def test_delivery_service_reuses_cached_manifest_and_returns_deep_copy(
    delivery_provider_factory: Callable[..., Any],
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
    delivery_provider_factory: Callable[..., Any],
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
    delivery_provider_factory: Callable[..., Any],
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
