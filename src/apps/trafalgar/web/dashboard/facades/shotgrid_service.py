"""ShotGrid aggregation helpers for the Trafalgar dashboard."""

from __future__ import annotations

from collections import Counter, defaultdict
from time import monotonic
from typing import Any, Callable, Iterable, Mapping, Sequence

import structlog

from ..auth import (
    _canonicalise_status,
    _extract_episode,
    _normalise_version_name,
    _parse_datetime,
)
from .project_registry import (
    _load_cache_configuration,
    _load_project_registry,
    _parse_float,
    _parse_int,
    _store_project_registry,
)

logger = structlog.get_logger(__name__)

__all__ = ["ShotGridService", "_coerce_project_name"]


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
        default_ttl, default_max_records, default_max_projects = _load_cache_configuration(
            state=state
        )
        ttl_source = cache_ttl if cache_ttl is not None else default_ttl
        max_records_source = (
            cache_max_records if cache_max_records is not None else default_max_records
        )
        max_projects_source = (
            cache_max_projects if cache_max_projects is not None else default_max_projects
        )
        self._cache_ttl: float = _parse_float(ttl_source, default_ttl)
        self._cache_max_records: int = _parse_int(max_records_source, default_max_records)
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
            self._cache_max_projects = _parse_int(max_projects, self._cache_max_projects)

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
            "episodes": sorted(episodes),
            "shots": len(shots),
            "versions": len(versions),
            "approved": approved,
            "status_totals": dict(sorted(status_totals.items())),
            "latest_versions": latest,
        }

    def project_episode_summary(self, project_name: str) -> dict[str, Any]:
        versions = self._filter_versions(project_name)

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

        episodes_payload: list[dict[str, Any]] = []
        payload = {
            "project": project_name,
            "episodes": episodes_payload,
            "status_totals": dict(sorted(overall_status.items())),
        }

        for name in sorted(episode_stats):
            stats = episode_stats[name]
            episodes_payload.append(
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
