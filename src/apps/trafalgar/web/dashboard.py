"""FastAPI dashboard exposing aggregated project status information."""

import hmac
import asyncio
import json
import os
from collections import Counter, OrderedDict, defaultdict
from functools import lru_cache
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from time import monotonic
from typing import Any, Awaitable, Callable, Hashable, Iterable, Mapping, Sequence
from urllib.parse import quote

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from apps.trafalgar.providers.providers import (
    DeliveryProvider,
    ReconcileDataProvider,
    initialize_providers,
)
from apps.trafalgar.version import TRAFALGAR_VERSION
from libraries.automation.delivery.manifest import get_manifest_data
from libraries.automation.reconcile import comparator
from .ingest_adapter import (
    IngestRunDashboardFacade,
    get_ingest_dashboard_facade,
)
from .render import RenderSubmissionService, get_render_service
from . import review as review_module
from libraries.automation.review.dailies import fetch_playlist_versions
from libraries.automation.review.dailies import DailiesClip
from libraries.integrations.shotgrid.api import ShotGridError

logger = structlog.get_logger(__name__)


# Canonical status mapping so that abbreviated and mixed-case values are
# aggregated consistently across dashboard views.
STATUS_CANONICAL_PREFIXES: OrderedDict[str, str] = OrderedDict(
    {
        "apr": "approved",
        "approved": "approved",
        "pub": "published",
        "published": "published",
        "final": "published",
    }
)


_DASHBOARD_TOKEN_ENV = "TRAFALGAR_DASHBOARD_TOKEN"
_bearer_scheme = HTTPBearer(auto_error=False)


def require_dashboard_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """Validate bearer token credentials for privileged dashboard endpoints."""

    expected_token = os.getenv(_DASHBOARD_TOKEN_ENV)
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="Dashboard authentication token is not configured.",
        )

    provided = credentials.credentials if credentials else None
    if not provided or not hmac.compare_digest(provided, expected_token):
        raise HTTPException(status_code=401, detail="Invalid authentication token.")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _parse_datetime(value: Any) -> Any:
    """Return an ISO 8601 timestamp for *value* if possible."""

    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    return None


def _extract_episode(record: Mapping[str, Any]) -> str | None:
    """Return the episode identifier for *record* if one can be derived."""

    episode = record.get("episode")
    if isinstance(episode, str) and episode.strip():
        return episode.strip()

    shot = record.get("shot")
    if isinstance(shot, str) and shot:
        return shot.split("_")[0]
    return None


def _normalise_version_name(record: Mapping[str, Any]) -> str | None:
    for key in ("version", "code", "version_number"):
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, int):
            return f"v{value:03d}"
        return str(value)
    return None


def _canonicalise_status(value: Any) -> str:
    if not value:
        return "unknown"

    text = str(value).strip().lower()
    if not text:
        return "unknown"

    for prefix, label in STATUS_CANONICAL_PREFIXES.items():
        if text.startswith(prefix):
            return label

    return text


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


def _load_cache_configuration() -> tuple[float, int, int]:
    """Return cache configuration from the environment or FastAPI state."""

    default_ttl = 30.0
    default_max_records = 5000
    default_max_projects = 50

    ttl_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_TTL")
    max_records_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_MAX_RECORDS")
    max_projects_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_MAX_PROJECTS")

    ttl = _parse_float(ttl_value, default_ttl)
    max_records = _parse_int(max_records_value, default_max_records)
    max_projects = _parse_int(max_projects_value, default_max_projects)

    try:  # pragma: no cover - FastAPI app may not be initialised in tests
        state = getattr(app, "state", None)
    except NameError:  # pragma: no cover - app not yet defined
        state = None

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


# ---------------------------------------------------------------------------
# ShotGrid aggregation
# ---------------------------------------------------------------------------


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
    ) -> None:
        self._client = client
        self._configured_projects = set(known_projects or [])
        self._fetcher = version_fetcher
        default_ttl, default_max_records, default_max_projects = (
            _load_cache_configuration()
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
        target_name = _coerce_project_name(project_name) or str(project_name).strip()

        versions = [
            version
            for version in self._fetch_versions()
            if (
                (
                    _coerce_project_name(version.get("project"))
                    or (
                        str(version.get("project")).strip()
                        if version.get("project") is not None
                        else None
                    )
                )
                == target_name
            )
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
        """
        Fetch versions from the configured client or fetcher.
        Supports three strategies:
        - self._fetcher callback
        - client.list_versions()
        - client.get_versions_for_project(name)
        """
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
            if isinstance(versions_raw, Sequence):
                versions_result = [dict(item) for item in versions_raw]
            else:
                versions_result = []
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
                    if isinstance(results, Sequence):
                        for item in results:
                            record = dict(item)
                            if not record.get("project"):
                                record["project"] = name
                            all_versions.append(record)
            versions_result = all_versions

        can_cache = self._cache_ttl > 0
        if can_cache and self._cache_max_records > 0:
            if len(versions_result) > self._cache_max_records:
                can_cache = False
        if can_cache and self._cache_max_projects > 0:
            project_count = len(
                {
                    _coerce_project_name(item.get("project"))
                    or str(item.get("project")).strip()
                    for item in versions_result
                    if item.get("project") is not None
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

        payload: dict[str, Any] = {
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


class ReconcileService:
    def __init__(
        self,
        provider: ReconcileDataProvider | str | None = None,
        *,
        comparator_fn: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        if isinstance(provider, str):
            self._provider = initialize_providers()
        else:
            self._provider = provider
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


# ---------------------------------------------------------------------------
# Dashboard response schemas
# ---------------------------------------------------------------------------


class IngestCountsModel(BaseModel):
    total: int = Field(0, ge=0)
    successful: int = Field(0, ge=0)
    failed: int = Field(0, ge=0)
    running: int = Field(0, ge=0)


class IngestSummaryModel(BaseModel):
    counts: IngestCountsModel
    last_success_at: str | None = None
    failure_streak: int = Field(0, ge=0)


class RenderSummaryModel(BaseModel):
    jobs: int = Field(0, ge=0)
    by_status: Mapping[str, int] = Field(default_factory=dict)
    by_farm: Mapping[str, int] = Field(default_factory=dict)


class ReviewProjectSummaryModel(BaseModel):
    project: str
    playlists: int = Field(0, ge=0)
    clips: int = Field(0, ge=0)
    shots: int = Field(0, ge=0)
    duration_seconds: float = Field(0.0, ge=0.0)


class ReviewTotalsModel(BaseModel):
    projects: int = Field(0, ge=0)
    playlists: int = Field(0, ge=0)
    clips: int = Field(0, ge=0)
    shots: int = Field(0, ge=0)
    duration_seconds: float = Field(0.0, ge=0.0)


class ReviewSummaryModel(BaseModel):
    totals: ReviewTotalsModel
    projects: Sequence[ReviewProjectSummaryModel] = Field(default_factory=list)


class StatusSummaryModel(BaseModel):
    projects: int = Field(0, ge=0)
    shots: int = Field(0, ge=0)
    versions: int = Field(0, ge=0)
    errors: int = Field(0, ge=0)


class DashboardMetricsModel(BaseModel):
    status: StatusSummaryModel
    ingest: IngestSummaryModel
    render: RenderSummaryModel
    review: ReviewSummaryModel


class CacheSettingsModel(BaseModel):
    ttl_seconds: float = Field(ge=0.0)
    max_records: int = Field(ge=0)
    max_projects: int = Field(ge=0)


class CacheSettingsUpdateModel(BaseModel):
    ttl_seconds: float | None = Field(default=None, ge=0.0)
    max_records: int | None = Field(default=None, ge=0)
    max_projects: int | None = Field(default=None, ge=0)
    flush: bool = False


class DeliveryService:
    def __init__(
        self,
        provider: DeliveryProvider | str | None = None,
        *,
        manifest_cache_size: int = 32,
    ) -> None:
        if isinstance(provider, str):
            self._provider = initialize_providers()
        else:
            self._provider = provider
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


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def get_shotgrid_client() -> Any:  # pragma: no cover - runtime wiring
    try:
        from libraries.integrations.shotgrid.client import ShotgridClient
    except ImportError:  # pragma: no cover - fallback if optional dependency missing
        ShotgridClient = None

    if ShotgridClient is None:
        raise RuntimeError("ShotgridClient is not available")
    return ShotgridClient()


@lru_cache(maxsize=1)
def get_shotgrid_service() -> ShotGridService:
    client = get_shotgrid_client()
    cache_ttl, cache_max_records, cache_max_projects = _load_cache_configuration()
    return ShotGridService(
        client,
        known_projects=_load_known_projects(),
        cache_ttl=cache_ttl,
        cache_max_records=cache_max_records,
        cache_max_projects=cache_max_projects,
    )


def get_reconcile_service() -> ReconcileService:
    return ReconcileService()


def get_delivery_service() -> DeliveryService:
    return DeliveryService()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


app = FastAPI(title="OnePiece Dashboard", version=TRAFALGAR_VERSION)
_TEMPLATE_CACHE: str | None = None


def discover_projects(shotgrid_service: ShotGridService | None = None) -> list[str]:
    """Return known projects, consulting ShotGrid when possible."""

    if shotgrid_service is None:
        override = app.dependency_overrides.get(get_shotgrid_service)
        provider: Callable[[], ShotGridService]
        if override is not None:
            provider = override
        else:
            provider = get_shotgrid_service
        try:
            shotgrid_service = provider()
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("dashboard.project_discovery.unavailable", error=str(exc))
            fallback = _load_known_projects().union(_load_project_registry())
            return sorted(fallback)

    try:
        return shotgrid_service.discover_projects()
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("dashboard.project_discovery.error", error=str(exc))
        fallback = _load_known_projects().union(_load_project_registry())
        return sorted(fallback)


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    logger.info(
        "dashboard.request.start",
        method=request.method,
        path=request.url.path,
    )
    response = await call_next(request)
    logger.info(
        "dashboard.request.complete",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    return response


def _load_landing_template() -> str:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        path = Path(__file__).parent / "templates" / "dashboard.html"
        _TEMPLATE_CACHE = path.read_text(encoding="utf-8")
    return _TEMPLATE_CACHE


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request) -> HTMLResponse:
    projects = discover_projects()
    example_project = projects[0] if projects else None

    nav_items: list[str] = [
        '<li><a href="{{BASE_PATH}}/status">Project status overview</a></li>',
    ]

    if example_project:
        safe_project = escape(example_project)
        encoded_project = quote(example_project, safe="")
        nav_items.extend(
            [
                f'<li><a href="{{BASE_PATH}}/projects/{encoded_project}">Summary for {safe_project}</a></li>',
                f'<li><a href="{{BASE_PATH}}/projects/{encoded_project}/episodes">Episode breakdown for {safe_project}</a></li>',
                f'<li><a href="{{BASE_PATH}}/deliveries/{encoded_project}">Deliveries for {safe_project}</a></li>',
            ]
        )
        review_link = f"{{BASE_PATH}}/review/projects/{encoded_project}/playlists"
    else:
        nav_items.extend(
            [
                "<li><code>/projects/&lt;project&gt;</code></li>",
                "<li><code>/projects/&lt;project&gt;/episodes</code></li>",
                "<li><code>/deliveries/&lt;project&gt;</code></li>",
            ]
        )
        review_link = "{{BASE_PATH}}/review/projects/example/playlists"

    nav_items.extend(
        [
            '<li><a href="{{BASE_PATH}}/errors">Reconciliation mismatches</a></li>',
            '<li><a href="{{BASE_PATH}}/errors/summary">Mismatch summary</a></li>',
            f'<li><a href="{review_link}">Review playlists API</a></li>',
        ]
    )

    template = _load_landing_template()
    projects_json = escape(json.dumps(projects), quote=True)
    nav_html = "\n        ".join(nav_items)
    raw_root_path = request.scope.get("root_path") or ""
    base_path = raw_root_path.rstrip("/") if raw_root_path else ""
    safe_base_path = escape(base_path, quote=True)
    html = (
        template.replace("{{PROJECTS_JSON}}", projects_json)
        .replace("{{NAV_ITEMS}}", nav_html)
        .replace("{{BASE_PATH}}", safe_base_path)
    )
    return HTMLResponse(content=html)


@app.get("/status")
async def status(
    shotgrid_service: ShotGridService = Depends(get_shotgrid_service),
    reconcile_service: ReconcileService = Depends(get_reconcile_service),
    ingest_facade: IngestRunDashboardFacade = Depends(get_ingest_dashboard_facade),
    render_facade: RenderDashboardFacade = Depends(get_render_dashboard_facade),
    review_facade: ReviewDashboardFacade = Depends(get_review_dashboard_facade),
) -> JSONResponse:
    summary = shotgrid_service.overall_status()
    errors = reconcile_service.list_errors()
    ingest_summary = ingest_facade.summarise_recent_runs()

    render_raw = await render_facade.summarise_jobs()
    if not isinstance(render_raw, Mapping):
        render_raw = {}
    render_summary = {
        "jobs": _parse_int(render_raw.get("jobs"), 0),
        "by_status": {
            str(key): _parse_int(value, 0)
            for key, value in dict(render_raw.get("by_status", {})).items()
        },
        "by_farm": {
            str(key): _parse_int(value, 0)
            for key, value in dict(render_raw.get("by_farm", {})).items()
        },
    }

    project_names = shotgrid_service.discover_projects()
    review_raw = review_facade.summarise_projects(project_names)
    if not isinstance(review_raw, Mapping):
        review_raw = {}
    review_projects_raw = list(review_raw.get("projects", []))
    review_projects = [
        {
            "project": str(entry.get("project")),
            "playlists": _parse_int(entry.get("playlists"), 0),
            "clips": _parse_int(entry.get("clips"), 0),
            "shots": _parse_int(entry.get("shots"), 0),
            "duration_seconds": _parse_float(entry.get("duration_seconds"), 0.0),
        }
        for entry in review_projects_raw
        if isinstance(entry, Mapping) and entry.get("project")
    ]
    review_totals_raw = (
        review_raw.get("totals", {}) if isinstance(review_raw, Mapping) else {}
    )
    review_summary = {
        "totals": {
            "projects": _parse_int(
                review_totals_raw.get("projects"), len(review_projects)
            ),
            "playlists": _parse_int(review_totals_raw.get("playlists"), 0),
            "clips": _parse_int(review_totals_raw.get("clips"), 0),
            "shots": _parse_int(review_totals_raw.get("shots"), 0),
            "duration_seconds": _parse_float(
                review_totals_raw.get("duration_seconds"), 0.0
            ),
        },
        "projects": review_projects,
    }

    payload = {
        **summary,
        "errors": len(errors),
        "ingest": ingest_summary,
        "render": render_summary,
        "review": review_summary,
    }
    return JSONResponse(content=payload)


@app.get(
    "/metrics",
    response_model=DashboardMetricsModel,
    dependencies=[Depends(require_dashboard_auth)],
)
async def metrics(
    shotgrid_service: ShotGridService = Depends(get_shotgrid_service),
    reconcile_service: ReconcileService = Depends(get_reconcile_service),
    ingest_facade: IngestRunDashboardFacade = Depends(get_ingest_dashboard_facade),
    render_facade: RenderDashboardFacade = Depends(get_render_dashboard_facade),
    review_facade: ReviewDashboardFacade = Depends(get_review_dashboard_facade),
) -> DashboardMetricsModel:
    status_summary = shotgrid_service.overall_status()
    error_count = len(reconcile_service.list_errors())

    ingest_raw = ingest_facade.summarise_recent_runs()
    ingest_counts_raw = (
        ingest_raw.get("counts", {}) if isinstance(ingest_raw, Mapping) else {}
    )
    ingest_counts = {
        str(key): _parse_int(value, 0) for key, value in dict(ingest_counts_raw).items()
    }
    ingest_model = IngestSummaryModel(
        counts=IngestCountsModel(**ingest_counts),
        last_success_at=(
            ingest_raw.get("last_success_at")
            if isinstance(ingest_raw, Mapping)
            else None
        ),
        failure_streak=(
            _parse_int(ingest_raw.get("failure_streak"), 0)
            if isinstance(ingest_raw, Mapping)
            else 0
        ),
    )

    render_raw = await render_facade.summarise_jobs()
    render_model = RenderSummaryModel(
        jobs=_parse_int(render_raw.get("jobs"), 0),
        by_status={
            str(key): _parse_int(value, 0)
            for key, value in dict(render_raw.get("by_status", {})).items()
        },
        by_farm={
            str(key): _parse_int(value, 0)
            for key, value in dict(render_raw.get("by_farm", {})).items()
        },
    )

    project_names = shotgrid_service.discover_projects()
    review_raw = review_facade.summarise_projects(project_names)
    review_projects_raw = (
        list(review_raw.get("projects", [])) if isinstance(review_raw, Mapping) else []
    )
    review_projects_model = [
        ReviewProjectSummaryModel(
            project=str(entry.get("project")),
            playlists=_parse_int(entry.get("playlists"), 0),
            clips=_parse_int(entry.get("clips"), 0),
            shots=_parse_int(entry.get("shots"), 0),
            duration_seconds=_parse_float(entry.get("duration_seconds"), 0.0),
        )
        for entry in review_projects_raw
        if isinstance(entry, Mapping) and entry.get("project")
    ]
    review_totals_raw = (
        review_raw.get("totals", {}) if isinstance(review_raw, Mapping) else {}
    )
    review_model = ReviewSummaryModel(
        totals=ReviewTotalsModel(
            projects=_parse_int(
                review_totals_raw.get("projects"), len(review_projects_model)
            ),
            playlists=_parse_int(review_totals_raw.get("playlists"), 0),
            clips=_parse_int(review_totals_raw.get("clips"), 0),
            shots=_parse_int(review_totals_raw.get("shots"), 0),
            duration_seconds=_parse_float(
                review_totals_raw.get("duration_seconds"), 0.0
            ),
        ),
        projects=review_projects_model,
    )

    status_model = StatusSummaryModel(
        projects=_parse_int(status_summary.get("projects"), 0),
        shots=_parse_int(status_summary.get("shots"), 0),
        versions=_parse_int(status_summary.get("versions"), 0),
        errors=error_count,
    )

    return DashboardMetricsModel(
        status=status_model,
        ingest=ingest_model,
        render=render_model,
        review=review_model,
    )


@app.get(
    "/admin/cache",
    response_model=CacheSettingsModel,
    dependencies=[Depends(require_dashboard_auth)],
)
async def get_cache_settings(
    shotgrid_service: ShotGridService = Depends(get_shotgrid_service),
) -> CacheSettingsModel:
    """Return the active cache configuration for the dashboard."""

    return CacheSettingsModel(**shotgrid_service.cache_settings)


@app.post(
    "/admin/cache",
    response_model=CacheSettingsModel,
    dependencies=[Depends(require_dashboard_auth)],
)
async def update_cache_settings(
    payload: CacheSettingsUpdateModel,
    shotgrid_service: ShotGridService = Depends(get_shotgrid_service),
) -> CacheSettingsModel:
    """Update cache configuration and optionally flush cached responses."""

    updates: dict[str, float | int] = {}
    if payload.ttl_seconds is not None:
        updates["ttl_seconds"] = payload.ttl_seconds
    if payload.max_records is not None:
        updates["max_records"] = payload.max_records
    if payload.max_projects is not None:
        updates["max_projects"] = payload.max_projects

    if updates:
        shotgrid_service.configure_cache(**updates)  # type: ignore[arg-type]
        settings = shotgrid_service.cache_settings
        if "ttl_seconds" in updates:
            app.state.dashboard_cache_ttl = settings["ttl_seconds"]
        if "max_records" in updates:
            app.state.dashboard_cache_max_records = settings["max_records"]
        if "max_projects" in updates:
            app.state.dashboard_cache_max_projects = settings["max_projects"]

    if payload.flush:
        shotgrid_service.invalidate_cache()

    return CacheSettingsModel(**shotgrid_service.cache_settings)


@app.get("/projects/{project_name}")
async def project_detail(
    project_name: str,
    shotgrid_service: ShotGridService = Depends(get_shotgrid_service),
) -> JSONResponse:
    try:
        summary = shotgrid_service.project_summary(project_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return JSONResponse(content=summary)


@app.get("/projects/{project_name}/episodes")
async def project_episode_detail(
    project_name: str,
    shotgrid_service: ShotGridService = Depends(get_shotgrid_service),
) -> JSONResponse:
    try:
        payload = shotgrid_service.project_episode_summary(project_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return JSONResponse(content=payload)


@app.get("/errors")
async def errors(
    reconcile_service: ReconcileService = Depends(get_reconcile_service),
) -> JSONResponse:
    mismatches = reconcile_service.list_errors()
    return JSONResponse(content=mismatches)


@app.get("/errors/summary")
async def error_summary(
    reconcile_service: ReconcileService = Depends(get_reconcile_service),
) -> JSONResponse:
    payload = reconcile_service.summarise_errors()
    return JSONResponse(content=payload)


@app.get("/deliveries/{project_name}")
async def deliveries(
    project_name: str,
    delivery_service: DeliveryService = Depends(get_delivery_service),
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> JSONResponse:
    include_manifest_api = False
    try:
        require_dashboard_auth(credentials)
    except HTTPException as exc:
        if exc.status_code not in (401, 503):
            raise
    else:
        include_manifest_api = True

    payload = delivery_service.list_deliveries(project_name)
    if include_manifest_api:
        project_fragment = quote(project_name, safe="")
        for entry in payload:
            identifier = entry.get("delivery_id") or entry.get("manifest")
            if not identifier:
                continue
            entry["manifest_api"] = (
                f"/deliveries/{project_fragment}/{quote(str(identifier), safe='')}"
            )
    return JSONResponse(content=payload)


@app.get(
    "/deliveries/{project_name}/{delivery_identifier:path}",
    dependencies=[Depends(require_dashboard_auth)],
)
async def delivery_manifest(
    project_name: str,
    delivery_identifier: str,
    delivery_service: DeliveryService = Depends(get_delivery_service),
) -> JSONResponse:
    try:
        manifest = delivery_service.get_delivery_manifest(
            project_name, delivery_identifier
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Delivery not found") from exc
    return JSONResponse(content=manifest)
