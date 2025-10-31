from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Type

import pytest

from apps.trafalgar.web import dashboard


def test_shotgrid_service_accepts_generator_versions() -> None:
    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "beta", "shot": "EP01_SC002_SH0010", "version": "v002"},
    ]

    class GeneratorShotgridClient:
        def list_versions(self) -> Iterable[dict[str, Any]]:
            return (dict(item) for item in versions)

    service = dashboard.ShotGridService(
        GeneratorShotgridClient(), known_projects={"alpha", "beta"}
    )

    fetched = service._fetch_versions()

    assert fetched == versions


def test_shotgrid_service_filters_versions_case_insensitively(
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    versions = [
        {"project": "ALPHA", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": {"name": "Alpha"}, "shot": "EP01_SC002_SH0020", "version": "v002"},
        {"project": "Alpha", "shot": "EP02_SC003_SH0030", "version": "v003"},
        {"project": "beta", "shot": "EP99_SC100_SH0500", "version": "v010"},
    ]

    service = dashboard.ShotGridService(dummy_shotgrid_client_cls(versions))

    filtered = service._filter_versions("aLpHa")

    assert [item["version"] for item in filtered] == ["v001", "v002", "v003"]
    assert filtered[0]["project"] == "ALPHA"
    assert filtered[1]["project"] == {"name": "Alpha"}
    assert filtered[2]["project"] == "Alpha"


def test_shotgrid_service_uses_default_provider() -> None:
    service = dashboard.ShotGridService()

    payload = service.overall_status()

    assert payload["versions"] == 0


def test_shotgrid_service_discovers_projects_and_updates_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    registry_path = tmp_path / "projects.json"
    monkeypatch.setenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY", str(registry_path))
    monkeypatch.delenv("ONEPIECE_DASHBOARD_PROJECTS", raising=False)

    versions: Sequence[dict[str, Any]] = [
        {"project": "alpha"},
        {"project": {"name": "beta"}},
        {"project": {"code": "alpha"}},
    ]

    client = dummy_shotgrid_client_cls(versions)
    service = dashboard.ShotGridService(client, known_projects={"omega"})

    projects = service.discover_projects()

    assert projects == ["alpha", "beta", "omega"]
    stored = json.loads(registry_path.read_text(encoding="utf-8"))
    assert stored == projects


def test_shotgrid_service_discover_projects_falls_back_to_cache_and_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    registry_path = tmp_path / "projects.json"
    registry_path.write_text(json.dumps(["cached"]), encoding="utf-8")
    monkeypatch.setenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY", str(registry_path))

    class OfflineShotgridClient(dummy_shotgrid_client_cls):  # type: ignore[misc]
        def list_versions(self) -> Sequence[dict[str, Any]]:
            raise RuntimeError("offline")

    service = dashboard.ShotGridService(
        OfflineShotgridClient([]),
        known_projects={"env_project"},
    )

    projects = service.discover_projects()

    assert projects == ["cached", "env_project"]


def test_shotgrid_service_discover_projects_handles_non_iterable_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    registry_path = tmp_path / "projects.json"
    monkeypatch.setenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY", str(registry_path))
    monkeypatch.delenv("ONEPIECE_DASHBOARD_PROJECTS", raising=False)

    class UnexpectedProjectClient(dummy_shotgrid_client_cls):  # type: ignore[misc]
        def list_projects(self) -> None:
            return None

    captured_events: list[tuple[str, dict[str, Any]]] = []

    class DummyLogger:
        def warning(self, event: str, **context: Any) -> None:
            captured_events.append((event, context))

    monkeypatch.setattr(dashboard, "logger", DummyLogger())

    client = UnexpectedProjectClient(
        [
            {"project": "omega"},
        ]
    )
    service = dashboard.ShotGridService(client, known_projects={"omega"})

    projects = service.discover_projects()

    assert projects == ["omega"]
    assert any(
        event == "dashboard.project_discovery.unexpected_projects_payload"
        for event, _ in captured_events
    )


def test_shotgrid_service_uses_discovered_projects_without_reinit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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


def test_shotgrid_service_caches_versions_until_ttl_expiry(
    dummy_shotgrid_client_cls: Type[Any],
    fake_monotonic_cls: Type[Any],
) -> None:
    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "alpha", "shot": "EP01_SC002_SH0010", "version": "v002"},
    ]
    client = dummy_shotgrid_client_cls(versions)
    clock = fake_monotonic_cls()

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


def test_shotgrid_service_skips_cache_when_dataset_exceeds_limit(
    dummy_shotgrid_client_cls: Type[Any],
    fake_monotonic_cls: Type[Any],
) -> None:
    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "alpha", "shot": "EP01_SC001_SH0020", "version": "v002"},
    ]
    client = dummy_shotgrid_client_cls(versions)
    clock = fake_monotonic_cls()

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


def test_shotgrid_service_skips_cache_when_project_count_exceeds_limit(
    dummy_shotgrid_client_cls: Type[Any],
    fake_monotonic_cls: Type[Any],
) -> None:
    versions = [
        {"project": "alpha", "shot": "EP01_SC001_SH0010", "version": "v001"},
        {"project": "beta", "shot": "EP01_SC002_SH0010", "version": "v002"},
    ]
    client = dummy_shotgrid_client_cls(versions)
    clock = fake_monotonic_cls()

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


def test_shotgrid_service_manual_invalidation_clears_cache(
    dummy_shotgrid_client_cls: Type[Any],
    fake_monotonic_cls: Type[Any],
) -> None:
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
        time_provider=clock,
    )

    first = service.overall_status()
    assert first["versions"] == 2
    assert client.calls == 1

    service.invalidate_cache()

    second = service.overall_status()
    assert second["versions"] == 2
    assert client.calls == 2


def test_shotgrid_service_overall_status_handles_mapping_projects(
    dummy_shotgrid_client_cls: Type[Any],
) -> None:
    versions: Sequence[dict[str, Any]] = [
        {"project": {"name": "alpha"}},
        {"project": {"name": {"value": "beta"}}},
        {"project": "alpha"},
    ]

    service = dashboard.ShotGridService(dummy_shotgrid_client_cls(versions))

    summary = service.overall_status()

    assert summary["projects"] == 2
