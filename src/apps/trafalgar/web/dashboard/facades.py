"""Facade classes and caching helpers for the Trafalgar dashboard."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Hashable, Iterable, Mapping, Sequence

import structlog

from apps.trafalgar.providers.providers import (
    DeliveryProvider,
    ProviderNotFoundError,
    ReconcileDataProvider,
    initialize_providers,
)
from libraries.automation.delivery.manifest import get_manifest_data
from libraries.automation.reconcile import comparator
from libraries.automation.review.dailies import DailiesClip, fetch_playlist_versions
from libraries.integrations.shotgrid.api import ShotGridError

from .. import review as review_module
from ..render import RenderSubmissionService, get_render_service
from .auth import (
    _canonicalise_status,
    _extract_episode,
    _normalise_version_name,
    _parse_datetime,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "ShotGridService",
    "ReconcileService",
    "DeliveryService",
    "RenderDashboardFacade",
    "ReviewDashboardFacade",
    "get_render_dashboard_facade",
    "get_review_dashboard_facade",
    "_load_known_projects",
    "_load_project_registry",
    "_store_project_registry",
    "_load_cache_configuration",
    "_coerce_project_name",
    "_parse_float",
    "_parse_int",
]


def _load_known_projects() -> set[str]:
    value = os.getenv("ONEPIECE_DASHBOARD_PROJECTS", "")
    projects = {item.strip() for item in value.split(",") if item.strip()}
    return projects


def _project_registry_path() -> Path | None:
    """Return the path used for caching discovered project names."""

    override = os.getenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY")
    if override:
        return Path(override)

    cache_root = os.getenv("XDG_CACHE_HOME")
    if cache_root:
        base = Path(cache_root)
    else:
        try:
            base = Path.home() / ".cache"
        except RuntimeError:  # pragma: no cover - extremely rare environments
            return None

    return base / "onepiece" / "dashboard-projects.json"


def _load_project_registry() -> set[str]:
    """Return cached project names from the local registry if available."""

    path = _project_registry_path()
    if path is None or not path.is_file():
        return set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "dashboard.project_registry.load_failed", path=str(path), error=str(exc)
        )
        return set()

    projects: set[str] = set()
    for item in data:
        if isinstance(item, str):
            text = item.strip()
            if text:
                projects.add(text)
        elif item is not None:
            text = str(item).strip()
            if text:
                projects.add(text)
    return projects


def _store_project_registry(projects: Iterable[str]) -> None:
    """Persist discovered project names for reuse when ShotGrid is offline."""

    path = _project_registry_path()
    if path is None:
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = sorted({str(item).strip() for item in projects if str(item).strip()})
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning(
            "dashboard.project_registry.store_failed", path=str(path), error=str(exc)
        )


def _coerce_project_name(value: Any) -> str | None:
    """Best effort extraction of a project name from ShotGrid responses."""

    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        return text or None

    if isinstance(value, Mapping):
        for key in ("name", "code", "project"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        # Some APIs return nested dictionaries (e.g. {"name": {"value": "..."}})
        for candidate in value.values():
            name = _coerce_project_name(candidate)
            if name:
                return name

    text = str(value).strip()
    return text or None


def _parse_float(value: Any, default: float) -> float:
    try:
        if value is None:
            raise ValueError("missing")
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            text = str(value).strip()
            if not text:
                raise ValueError("empty")
            result = float(text)
    except (TypeError, ValueError):
        return max(0.0, float(default))
    return max(0.0, float(result))


def _parse_int(value: Any, default: int) -> int:
    try:
        if value is None:
            raise ValueError("missing")
        if isinstance(value, int):
            result = value
        else:
            text = str(value).strip()
            if not text:
                raise ValueError("empty")
            result = int(text)
    except (TypeError, ValueError):
        return max(0, int(default))
    return max(0, int(result))


def _load_cache_configuration(*, state: Any | None = None) -> tuple[float, int, int]:
    """Return cache configuration from the environment or provided state."""

    default_ttl = 30.0
    default_max_records = 5000
    default_max_projects = 50

    ttl_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_TTL")
    max_records_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_MAX_RECORDS")
    max_projects_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_MAX_PROJECTS")

    ttl = _parse_float(ttl_value, default_ttl)
    max_records = _parse_int(max_records_value, default_max_records)
    max_projects = _parse_int(max_projects_value, default_max_projects)

    if state is not None:
        ttl = _parse_float(getattr(state, "dashboard_cache_ttl", ttl), ttl)
        max_records = _parse_int(
            getattr(state, "dashboard_cache_max_records", max_records),
            max_records,
        )
        max_projects = _parse_int(
            getattr(state, "dashboard_cache_max_projects", max_projects),
            max_projects,
        )

    return ttl, max_records, max_projects


class ShotGridService:
    """Aggregate project data using a ShotGrid client."""

    def __init__(
        self,
        client: Any,
        *,
        known_projects: Iterable[str] | None = None,
        version_fetcher: Callable[[Any], Sequence[Mapping[str, Any]]] | None = None,
        cache_ttl: float | int | None = None,
        cache_max_records: int | None = None,
        cache_max_projects: int | None = None,
        time_provider: Callable[[], float] | None = None,
        state: Any | None = None,
    ) -> None:
        self._client = client
        self._configured_projects = set(known_projects or [])
        self._fetcher = version_fetcher
        default_ttl, default_max_records, default_max_projects = (
            _load_cache_configuration(state=state)
        )
        ttl_source = cache_ttl if cache_ttl is not None else default_ttl
        max_records_source = (
            cache_max_records if cache_max_records is not None else default_max_records
        )
        max_projects_source = (
            cache_max_projects
            if cache_max_projects is not None
            else default_max_projects
        )
        self._cache_ttl: float = _parse_float(ttl_source, default_ttl)
        self._cache_max_records: int = _parse_int(
            max_records_source, default_max_records
        )
        self._cache_max_projects: int = _parse_int(
            max_projects_source, default_max_projects
        )
        self._time_provider = time_provider or monotonic
        self._version_cache: dict[
            tuple[Any, ...], tuple[float, list[Mapping[str, Any]]]
        ] = {}

    @property
    def cache_settings(self) -> dict[str, float | int]:
        """Return the current cache settings."""

        return {
            "ttl_seconds": self._cache_ttl,
            "max_records": self._cache_max_records,
            "max_projects": self._cache_max_projects,
        }

    def configure_cache(
        self,
        *,
        ttl_seconds: float | int | None = None,
        max_records: int | None = None,
        max_projects: int | None = None,
    ) -> None:
        """Adjust cache settings at runtime."""

        if ttl_seconds is not None:
            self._cache_ttl = _parse_float(ttl_seconds, self._cache_ttl)
        if max_records is not None:
            self._cache_max_records = _parse_int(max_records, self._cache_max_records)
        if max_projects is not None:
            self._cache_max_projects = _parse_int(
                max_projects, self._cache_max_projects
            )

    def invalidate_cache(self) -> None:
        """Clear cached ShotGrid responses."""

        self._version_cache.clear()

    def discover_projects(self) -> list[str]:
        """Return a sorted list of known projects using ShotGrid if available."""

        projects = {item.strip() for item in self._configured_projects if item.strip()}
        projects.update(_load_project_registry())

        try:
            fetch_projects = getattr(self._client, "list_projects", None)
            if callable(fetch_projects):
                records = fetch_projects()
                if not isinstance(records, Iterable):
                    logger.warning(
                        "dashboard.project_discovery.unexpected_projects_payload",
                        payload_type=type(records).__name__,
                    )
                    records = []

                for record in records:
                    name = _coerce_project_name(record)
                    if name:
                        projects.add(name)
            else:
                for record in self._fetch_versions():
                    name = _coerce_project_name(record.get("project"))
                    if name:
                        projects.add(name)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("dashboard.project_discovery.failed", error=str(exc))
            return sorted(projects)

        if projects:
            _store_project_registry(projects)

        discovered = sorted(projects)
        self._configured_projects = set(discovered)

        return discovered

    def _filter_versions(self, project_name: str) -> list[Mapping[str, Any]]:
        def _canonical_project_key(value: Any) -> str:
            coerced = _coerce_project_name(value)
            if coerced is None:
                text = str(value).strip()
            else:
                text = coerced
            return text.casefold()

        target_key = _canonical_project_key(project_name)

        versions = [
            version
            for version in self._fetch_versions()
            if _canonical_project_key(version.get("project")) == target_key
        ]

        if not versions and project_name not in self._configured_projects:
            raise KeyError(project_name)

        return versions

    def _cache_key(self) -> tuple[Any, ...]:
        return (
            "versions",
            tuple(sorted(self._configured_projects)),
            self._fetcher,
        )

    def _fetch_versions(self) -> list[Mapping[str, Any]]:
        """Fetch versions from the configured client or fetcher."""

        cache_key = self._cache_key()
        now = self._time_provider()

        if self._cache_ttl > 0:
            cached = self._version_cache.get(cache_key)
            if cached is not None:
                expires_at, cached_versions = cached
                if expires_at > now:
                    return [dict(item) for item in cached_versions]

        if self._fetcher is not None:
            fetcher: Callable[[Any], Sequence[Mapping[str, Any]]] = self._fetcher
            versions_result = list(fetcher(self._client))
        elif hasattr(self._client, "list_versions"):
            versions_raw: Any = getattr(self._client, "list_versions")()
            if isinstance(versions_raw, Sequence) and not isinstance(
                versions_raw, (str, bytes)
            ):
                versions_iterable: Iterable[Mapping[str, Any]] = versions_raw
            elif isinstance(versions_raw, Iterable) and not isinstance(
                versions_raw, (str, bytes)
            ):
                versions_iterable = versions_raw
            else:
                versions_iterable = []
            versions_result = [dict(item) for item in versions_iterable]
        else:
            project_names: set[str] = set(self._configured_projects)
            all_versions: list[Mapping[str, Any]] = []
            if project_names and hasattr(self._client, "get_versions_for_project"):
                fetch = getattr(self._client, "get_versions_for_project")
                for name in project_names:
                    try:
                        results: Any = fetch(name)
                    except Exception as exc:  # pragma: no cover
                        logger.warning(
                            "dashboard.fetch_versions_failed",
                            project=name,
                            error=str(exc),
                        )
                        continue
                    if isinstance(results, Sequence) and not isinstance(
                        results, (str, bytes)
                    ):
                        results_iterable: Iterable[Mapping[str, Any]] = results
                    elif isinstance(results, Iterable) and not isinstance(
                        results, (str, bytes)
                    ):
                        results_iterable = results
                    else:
                        results_iterable = []
                    for item in results_iterable:
                        record = dict(item)
                        record.setdefault("project", name)
                        all_versions.append(record)
            else:
                all_versions = []

            versions_result = all_versions

        can_cache = self._cache_ttl > 0
        if can_cache and self._cache_max_records > 0:
            if len(versions_result) > self._cache_max_records:
                can_cache = False
        if can_cache and self._cache_max_projects > 0:
            project_count = len(
                {
                    _coerce_project_name(version.get("project")) or ""
                    for version in versions_result
                }
            )
            if project_count > self._cache_max_projects:
                can_cache = False

        if can_cache:
            self._version_cache[cache_key] = (
                now + self._cache_ttl,
                [dict(item) for item in versions_result],
            )

        else:
            self._version_cache.pop(cache_key, None)

        return [dict(item) for item in versions_result]

    def list_projects(self) -> list[str]:
        """Return the configured projects list."""

        return sorted(self._configured_projects)

    def list_versions(self) -> list[Mapping[str, Any]]:
        return self._fetch_versions()

    def _project_names(self, versions: Iterable[Mapping[str, Any]]) -> set[str]:
        names = {
            name for v in versions if (name := _coerce_project_name(v.get("project")))
        }
        names.update(self._configured_projects)
        return {name for name in names if name}

    def overall_status(self) -> dict[str, Any]:
        versions = self._fetch_versions()
        projects = self._project_names(versions)
        shots = {
            (str(v.get("project")), str(v.get("shot")))
            for v in versions
            if v.get("project") and v.get("shot")
        }
        return {
            "projects": len(projects),
            "shots": len(shots),
            "versions": len(versions),
        }

    def project_summary(self, project_name: str) -> dict[str, Any]:
        versions = self._filter_versions(project_name)

        episodes = {
            episode for record in versions if (episode := _extract_episode(record))
        }
        shots = {str(record.get("shot")) for record in versions if record.get("shot")}
        approved = sum(
            1
            for record in versions
            if _canonicalise_status(record.get("status")) == "approved"
        )
        published = [
            record
            for record in versions
            if _canonicalise_status(record.get("status")) == "published"
        ]

        status_totals: Counter[str] = Counter()
        for record in versions:
            key = _canonicalise_status(record.get("status"))
            status_totals[key] += 1

        published.sort(
            key=lambda item: _parse_datetime(
                item.get("timestamp")
                or item.get("published_at")
                or item.get("updated_at")
                or item.get("created_at")
            )
            or "",
            reverse=True,
        )

        latest = []
        for record in published[:5]:
            latest.append(
                {
                    "shot": record.get("shot"),
                    "version": _normalise_version_name(record),
                    "user": record.get("user"),
                    "timestamp": _parse_datetime(
                        record.get("timestamp")
                        or record.get("published_at")
                        or record.get("updated_at")
                        or record.get("created_at")
                    ),
                }
            )

        return {
            "project": project_name,
            "episodes": len(episodes),
            "shots": len(shots),
            "versions": len(versions),
            "approved_versions": approved,
            "status_totals": dict(sorted(status_totals.items())),
            "latest_published": latest,
        }

    def project_episode_summary(self, project_name: str) -> dict[str, Any]:
        versions = self._filter_versions(project_name)

        payload: dict[str, Any] = {
            "project": project_name,
            "episodes": [],
            "status_totals": Counter(),
            "versions": [],
        }

        episode_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "shots": set(),
                "versions": 0,
                "status_counts": Counter(),
            }
        )
        overall_status: Counter[str] = Counter()

        for record in versions:
            episode = _extract_episode(record) or "unassigned"
            stats = episode_stats[episode]
            shot = record.get("shot")
            if shot:
                stats["shots"].add(str(shot))
            stats["versions"] += 1

            key = _canonicalise_status(record.get("status"))
            stats["status_counts"][key] += 1
            overall_status[key] += 1

        payload = {
            "project": project_name,
            "episodes": [],
            "status_totals": dict(sorted(overall_status.items())),
        }

        for name in sorted(episode_stats):
            stats = episode_stats[name]
            payload["episodes"].append(
                {
                    "episode": name,
                    "shots": len(stats["shots"]),
                    "versions": stats["versions"],
                    "status_counts": dict(sorted(stats["status_counts"].items())),
                }
            )

        return payload

    def summarise_project(self, project_name: str) -> dict[str, Any]:
        return self.project_episode_summary(project_name)

    def summarise_versions(self, project_name: str) -> list[dict[str, Any]]:
        versions = self._filter_versions(project_name)
        payload: list[dict[str, Any]] = []

        for record in versions:
            payload.append(
                {
                    "id": record.get("id"),
                    "shot": record.get("shot"),
                    "episode": _extract_episode(record),
                    "status": _canonicalise_status(record.get("status")),
                    "version": _normalise_version_name(record),
                    "created_at": _parse_datetime(record.get("created_at")),
                    "updated_at": _parse_datetime(record.get("updated_at")),
                }
            )

        return payload

    def summarise_status(self, project_name: str | None = None) -> dict[str, Any]:
        versions = (
            self._fetch_versions()
            if project_name is None
            else self._filter_versions(project_name)
        )

        projects: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "episodes": defaultdict(lambda: Counter()),
                "shot_counts": defaultdict(int),
                "status_totals": Counter(),
                "version_totals": 0,
            }
        )

        for record in versions:
            project = _coerce_project_name(record.get("project")) or "unknown"
            episode = _extract_episode(record) or "unassigned"
            status = _canonicalise_status(record.get("status"))
            shot = record.get("shot")

            project_data = projects[project]
            project_data["episodes"][episode][status] += 1
            project_data["status_totals"][status] += 1
            project_data["version_totals"] += 1

            if shot:
                project_data["shot_counts"][episode] += 1

        project_summary: list[dict[str, Any]] = []
        total_shots = 0
        total_versions = 0
        total_errors = 0

        for project, data in sorted(projects.items()):
            episodes_payload: list[dict[str, Any]] = []
            for episode, counts in sorted(data["episodes"].items()):
                shot_count = data["shot_counts"].get(episode, 0)
                episodes_payload.append(
                    {
                        "episode": episode,
                        "shot_count": shot_count,
                        "status_counts": dict(sorted(counts.items())),
                    }
                )
            project_summary.append(
                {
                    "project": project,
                    "episodes": episodes_payload,
                    "status_totals": dict(sorted(data["status_totals"].items())),
                    "version_totals": data["version_totals"],
                }
            )

            total_shots += sum(data["shot_counts"].values())
            total_versions += data["version_totals"]
            total_errors += data["status_totals"].get("failed", 0)

        return {
            "projects": len(project_summary),
            "shots": total_shots,
            "versions": total_versions,
            "errors": total_errors,
            "project_breakdown": project_summary,
        }


def _resolve_reconcile_provider(
    provider: ReconcileDataProvider | str | None,
) -> ReconcileDataProvider:
    """Return a :class:`ReconcileDataProvider` instance for *provider*."""

    if isinstance(provider, ReconcileDataProvider):
        return provider

    if provider is not None and not isinstance(provider, str):
        msg = (
            "ReconcileService provider must be a ReconcileDataProvider instance,"
            " a provider name, or None."
        )
        raise TypeError(msg)

    registry = initialize_providers()
    try:
        if isinstance(provider, str):
            resolved = registry.create("reconcile", provider)
        else:
            resolved = registry.create_default("reconcile")
    except ProviderNotFoundError as exc:
        if provider is None:
            msg = "No default reconcile provider is configured."
        else:
            msg = f"Unknown reconcile provider '{provider}'."
        raise RuntimeError(msg) from exc

    if not isinstance(resolved, ReconcileDataProvider):
        msg = (
            "Resolved reconcile provider does not implement ReconcileDataProvider: "
            f"{type(resolved).__name__}"
        )
        raise TypeError(msg)

    return resolved


class ReconcileService:
    def __init__(
        self,
        provider: ReconcileDataProvider | str | None = None,
        *,
        comparator_fn: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._provider = _resolve_reconcile_provider(provider)
        self._comparator = comparator_fn or comparator.compare_datasets

    def list_errors(self) -> list[Mapping[str, Any]]:
        payload = self._provider.load()
        shotgrid = payload.get("shotgrid", [])
        filesystem = payload.get("filesystem", [])
        s3 = payload.get("s3")
        return list(self._comparator(shotgrid, filesystem, s3=s3))

    def summarise_errors(self) -> list[dict[str, Any]]:
        mismatches = self.list_errors()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}

        for mismatch in mismatches:
            mismatch_type = str(mismatch.get("type") or "unknown")
            path_value = ""
            for key in ("path", "key"):
                value = mismatch.get(key)
                if value:
                    path_value = str(value)
                    break
            group = grouped.setdefault(
                (mismatch_type, path_value),
                {"type": mismatch_type, "path": path_value, "count": 0, "shots": set()},
            )
            group["count"] += 1
            shot = mismatch.get("shot")
            if shot:
                group["shots"].add(str(shot))

        summary: list[dict[str, Any]] = []
        for _, data in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1])
        ):
            summary.append(
                {
                    "type": data["type"],
                    "path": data["path"],
                    "count": data["count"],
                    "shots": sorted(data["shots"]),
                }
            )

        return summary


def _resolve_delivery_provider(
    provider: DeliveryProvider | str | None,
) -> DeliveryProvider:
    """Return a :class:`DeliveryProvider` instance for *provider*."""

    if isinstance(provider, DeliveryProvider):
        return provider

    if provider is not None and not isinstance(provider, str):
        msg = (
            "DeliveryService provider must be a DeliveryProvider instance,"
            " a provider name, or None."
        )
        raise TypeError(msg)

    registry = initialize_providers()
    try:
        if isinstance(provider, str):
            resolved = registry.create("delivery", provider)
        else:
            resolved = registry.create_default("delivery")
    except ProviderNotFoundError as exc:
        if provider is None:
            msg = "No default delivery provider is configured."
        else:
            msg = f"Unknown delivery provider '{provider}'."
        raise RuntimeError(msg) from exc

    if not isinstance(resolved, DeliveryProvider):
        msg = (
            "Resolved delivery provider does not implement DeliveryProvider: "
            f"{type(resolved).__name__}"
        )
        raise TypeError(msg)

    return resolved


class DeliveryService:
    def __init__(
        self,
        provider: DeliveryProvider | str | None = None,
        *,
        manifest_cache_size: int = 32,
    ) -> None:
        self._provider = _resolve_delivery_provider(provider)
        self._manifest_cache: OrderedDict[Hashable, dict[str, Any]] = OrderedDict()
        self._manifest_cache_size = max(0, manifest_cache_size)

    def _manifest_cache_key(self, delivery: Mapping[str, Any]) -> Hashable | None:
        for key in ("id", "delivery_id"):
            value = delivery.get(key)
            if isinstance(value, Hashable):
                return value
        return None

    def _delivery_cache_keys(self, delivery: Mapping[str, Any]) -> list[Hashable]:
        keys: list[Hashable] = []
        cache_key = self._manifest_cache_key(delivery)
        if cache_key is not None:
            keys.append(cache_key)
        manifest_path = delivery.get("manifest")
        if isinstance(manifest_path, str) and manifest_path:
            keys.append(manifest_path)
        return keys

    @staticmethod
    def _clone_manifest_data(manifest: Mapping[str, Any]) -> dict[str, Any]:
        files = manifest.get("files", [])
        if isinstance(files, Sequence) and not isinstance(
            files, (str, bytes, bytearray)
        ):
            cloned_files = [
                dict(item) if isinstance(item, Mapping) else item for item in files
            ]
        else:
            cloned_files = []
        return {"files": cloned_files}

    def _store_manifest(self, key: Hashable, manifest: Mapping[str, Any]) -> None:
        if self._manifest_cache_size == 0:
            return
        self._manifest_cache[key] = self._clone_manifest_data(manifest)
        self._manifest_cache.move_to_end(key)
        while len(self._manifest_cache) > self._manifest_cache_size:
            self._manifest_cache.popitem(last=False)

    def _lookup_manifest(self, key: Hashable) -> dict[str, Any] | None:
        if self._manifest_cache_size == 0:
            return None
        cached = self._manifest_cache.get(key)
        if cached is None:
            return None
        self._manifest_cache.move_to_end(key)
        return self._clone_manifest_data(cached)

    @staticmethod
    def _normalise_manifest_payload(
        payload: Any,
    ) -> dict[str, Any] | None:
        if isinstance(payload, Mapping):
            return DeliveryService._clone_manifest_data(payload)
        if isinstance(payload, Sequence) and not isinstance(
            payload, (str, bytes, bytearray)
        ):
            files = [
                dict(item) if isinstance(item, Mapping) else item for item in payload
            ]
            return {"files": files}
        return None

    def list_deliveries(self, project_name: str) -> list[dict[str, Any]]:
        deliveries = self._provider.list_deliveries(project_name)
        result: list[dict[str, Any]] = []
        for delivery in deliveries:
            entries = delivery.get("entries") or []
            manifest_data = self._normalise_manifest_payload(
                delivery.get("manifest_data")
            )
            if manifest_data is None:
                manifest_data = self._normalise_manifest_payload(delivery.get("items"))

            cache_keys = self._delivery_cache_keys(delivery)
            cached_from: Hashable | None = None
            if manifest_data is None:
                for key in cache_keys:
                    cached_manifest = self._lookup_manifest(key)
                    if cached_manifest is not None:
                        manifest_data = cached_manifest
                        cached_from = key
                        break

            if manifest_data is None:
                if entries:
                    manifest_data = get_manifest_data(entries)
                else:
                    manifest_data = {"files": []}

            for key in cache_keys:
                if cached_from is not None and key == cached_from:
                    continue
                self._store_manifest(key, manifest_data)

            files = manifest_data.get("files", [])
            cache_key = self._manifest_cache_key(delivery)
            result.append(
                {
                    "project": project_name,
                    "name": delivery.get("name"),
                    "archive": delivery.get("archive"),
                    "manifest": delivery.get("manifest"),
                    "delivery_id": str(cache_key) if cache_key is not None else None,
                    "created_at": _parse_datetime(
                        delivery.get("created_at") or delivery.get("timestamp")
                    ),
                    "items": files,
                    "file_count": len(files),
                }
            )
        return result

    def get_delivery_manifest(
        self, project_name: str, identifier: str
    ) -> dict[str, Any]:
        lookup = identifier.strip()
        if not lookup:
            raise KeyError("Empty delivery identifier")

        deliveries = self._provider.list_deliveries(project_name)
        for delivery in deliveries:
            cache_keys = self._delivery_cache_keys(delivery)
            if not any(str(key) == lookup for key in cache_keys):
                continue

            for key in cache_keys:
                cached_manifest = self._lookup_manifest(key)
                if cached_manifest is not None:
                    return cached_manifest

            entries = delivery.get("entries") or []
            manifest_data = self._normalise_manifest_payload(
                delivery.get("manifest_data")
            )
            if manifest_data is None:
                manifest_data = self._normalise_manifest_payload(delivery.get("items"))
            if manifest_data is None:
                if entries:
                    manifest_data = get_manifest_data(entries)
                else:
                    manifest_data = {"files": []}

            for key in cache_keys:
                self._store_manifest(key, manifest_data)
            return manifest_data

        raise KeyError(f"Delivery not found: {identifier}")


class RenderDashboardFacade:
    """Aggregate render job metrics for dashboard consumption."""

    def __init__(self, service: RenderSubmissionService | None = None) -> None:
        self._service = service or get_render_service()

    async def summarise_jobs(self) -> dict[str, Any]:
        jobs = await asyncio.to_thread(self._service.list_jobs)
        status_counts: Counter[str] = Counter()
        farm_counts: Counter[str] = Counter()
        for job in jobs:
            status_counts[str(job.status).lower()] += 1
            farm_counts[str(job.farm)] += 1
        return {
            "jobs": len(jobs),
            "by_status": dict(sorted(status_counts.items())),
            "by_farm": dict(sorted(farm_counts.items())),
        }


class ReviewDashboardFacade:
    """Summarise review playlist activity across projects."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client or review_module.get_shotgrid_client()

    def summarise_projects(self, project_names: Iterable[str]) -> dict[str, Any]:
        project_summaries: list[dict[str, Any]] = []
        total_playlists = 0
        total_clips = 0
        total_shots = 0
        total_duration = 0.0

        for project in project_names:
            try:
                playlists = review_module._list_project_playlists(  # noqa: SLF001
                    self._client, project
                )
            except ShotGridError as exc:
                logger.warning(
                    "dashboard.review.playlists_failed",
                    project=project,
                    error=str(exc),
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "dashboard.review.playlists_error",
                    project=project,
                    error=str(exc),
                )
                continue

            playlists_processed = 0
            project_clips = 0
            project_shots = 0
            project_duration = 0.0

            for playlist in playlists:
                try:
                    clips: Iterable[DailiesClip] = fetch_playlist_versions(
                        self._client, project, playlist
                    )
                except ShotGridError as exc:
                    logger.warning(
                        "dashboard.review.playlist_summary_failed",
                        project=project,
                        playlist=playlist,
                        error=str(exc),
                    )
                    continue
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.warning(
                        "dashboard.review.playlist_summary_error",
                        project=project,
                        playlist=playlist,
                        error=str(exc),
                    )
                    continue

                summary = review_module._summarise_clips(clips)  # noqa: SLF001
                playlists_processed += 1
                project_clips += int(summary.get("clips", 0))
                project_shots += int(summary.get("shots", 0))
                project_duration += float(summary.get("duration_seconds", 0.0))

            total_playlists += playlists_processed
            total_clips += project_clips
            total_shots += project_shots
            total_duration += project_duration

            project_summaries.append(
                {
                    "project": project,
                    "playlists": playlists_processed,
                    "clips": project_clips,
                    "shots": project_shots,
                    "duration_seconds": project_duration,
                }
            )

        return {
            "totals": {
                "projects": len(project_summaries),
                "playlists": total_playlists,
                "clips": total_clips,
                "shots": total_shots,
                "duration_seconds": total_duration,
            },
            "projects": project_summaries,
        }


def get_render_dashboard_facade() -> RenderDashboardFacade:  # pragma: no cover - wiring
    return RenderDashboardFacade()


def get_review_dashboard_facade() -> ReviewDashboardFacade:  # pragma: no cover - wiring
    return ReviewDashboardFacade()
