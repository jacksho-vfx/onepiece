"""FastAPI dashboard exposing aggregated project status information."""

import json
import os
from collections import Counter, defaultdict
from functools import lru_cache
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Iterable, Mapping, Sequence, Awaitable
from urllib.parse import quote

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from apps.trafalgar.version import TRAFALGAR_VERSION
from libraries.delivery.manifest import get_manifest_data
from libraries.reconcile import comparator
from .ingest_adapter import (
    IngestRunDashboardFacade,
    get_ingest_dashboard_facade,
)

logger = structlog.get_logger(__name__)


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


def _is_status(status: Any, expected: Sequence[str]) -> bool:
    if not status:
        return False
    text = str(status).lower()
    return any(text.startswith(prefix) for prefix in expected)


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


def _load_cache_configuration() -> tuple[float, int]:
    """Return cache configuration from the environment or FastAPI state."""

    default_ttl = 30.0
    default_max_records = 5000

    ttl_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_TTL")
    max_records_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_MAX_RECORDS")

    ttl = _parse_float(ttl_value, default_ttl)
    max_records = _parse_int(max_records_value, default_max_records)

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

    return ttl, max_records


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
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._configured_projects = set(known_projects or [])
        self._fetcher = version_fetcher
        default_ttl, default_max_records = _load_cache_configuration()
        ttl_source = cache_ttl if cache_ttl is not None else default_ttl
        max_records_source = (
            cache_max_records if cache_max_records is not None else default_max_records
        )
        self._cache_ttl: float = _parse_float(ttl_source, default_ttl)
        self._cache_max_records: int = _parse_int(
            max_records_source, default_max_records
        )
        self._time_provider = time_provider or monotonic
        self._version_cache: dict[
            tuple[Any, ...], tuple[float, list[Mapping[str, Any]]]
        ] = {}

    def discover_projects(self) -> list[str]:
        """Return a sorted list of known projects using ShotGrid if available."""

        projects = {item.strip() for item in self._configured_projects if item.strip()}
        projects.update(_load_project_registry())

        try:
            fetch_projects = getattr(self._client, "list_projects", None)
            if callable(fetch_projects):
                records = fetch_projects()
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

        return sorted(projects)

    def _filter_versions(self, project_name: str) -> list[Mapping[str, Any]]:
        versions = [
            version
            for version in self._fetch_versions()
            if str(version.get("project")) == project_name
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
                        all_versions.extend(dict(item) for item in results)
            versions_result = all_versions

        can_cache = self._cache_ttl > 0
        if can_cache and self._cache_max_records > 0:
            if len(versions_result) > self._cache_max_records:
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
        names = {str(v.get("project")) for v in versions if v.get("project")}
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
            if _is_status(record.get("status"), ("apr", "approved"))
        )
        published = [
            record
            for record in versions
            if _is_status(record.get("status"), ("pub", "published", "final"))
        ]

        status_totals: Counter[str] = Counter()
        for record in versions:
            status = record.get("status")
            key = str(status).strip().lower() if status else "unknown"
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

            status = record.get("status")
            key = str(status).strip().lower() if status else "unknown"
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


# ---------------------------------------------------------------------------
# Reconciliation aggregation
# ---------------------------------------------------------------------------


class ReconcileDataProvider:
    """Return reconciliation datasets used for mismatch detection."""

    def load(self) -> dict[str, Any]:  # pragma: no cover - default behaviour
        return {"shotgrid": [], "filesystem": [], "s3": None}


class ReconcileService:
    def __init__(
        self,
        provider: ReconcileDataProvider | None = None,
        *,
        comparator_fn: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._provider = provider or ReconcileDataProvider()
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


# ---------------------------------------------------------------------------
# Delivery aggregation
# ---------------------------------------------------------------------------


class DeliveryProvider:
    """Provide delivery metadata for dashboard views."""

    def list_deliveries(
        self, project_name: str
    ) -> Sequence[Mapping[str, Any]]:  # pragma: no cover
        return []


class DeliveryService:
    def __init__(self, provider: DeliveryProvider | None = None) -> None:
        self._provider = provider or DeliveryProvider()

    def list_deliveries(self, project_name: str) -> list[dict[str, Any]]:
        deliveries = self._provider.list_deliveries(project_name)
        result: list[dict[str, Any]] = []
        for delivery in deliveries:
            entries = delivery.get("entries", [])
            manifest = get_manifest_data(entries)
            result.append(
                {
                    "project": project_name,
                    "name": delivery.get("name"),
                    "archive": delivery.get("archive"),
                    "manifest": delivery.get("manifest"),
                    "created_at": _parse_datetime(
                        delivery.get("created_at") or delivery.get("timestamp")
                    ),
                    "items": manifest.get("files", []),
                    "file_count": len(manifest.get("files", [])),
                }
            )
        return result


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def get_shotgrid_client() -> Any:  # pragma: no cover - runtime wiring
    try:
        from libraries.shotgrid.client import ShotgridClient
    except ImportError:  # pragma: no cover - fallback if optional dependency missing
        ShotgridClient = None

    if ShotgridClient is None:
        raise RuntimeError("ShotgridClient is not available")
    return ShotgridClient()


@lru_cache(maxsize=1)
def get_shotgrid_service() -> ShotGridService:
    client = get_shotgrid_client()
    cache_ttl, cache_max_records = _load_cache_configuration()
    return ShotGridService(
        client,
        known_projects=_load_known_projects(),
        cache_ttl=cache_ttl,
        cache_max_records=cache_max_records,
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
        '<li><a href="/status">Project status overview</a></li>',
    ]

    if example_project:
        safe_project = escape(example_project)
        encoded_project = quote(example_project, safe="")
        nav_items.extend(
            [
                f'<li><a href="/projects/{encoded_project}">Summary for {safe_project}</a></li>',
                f'<li><a href="/projects/{encoded_project}/episodes">Episode breakdown for {safe_project}</a></li>',
                f'<li><a href="/deliveries/{encoded_project}">Deliveries for {safe_project}</a></li>',
            ]
        )
        review_link = f"/review/projects/{encoded_project}/playlists"
    else:
        nav_items.extend(
            [
                "<li><code>/projects/&lt;project&gt;</code></li>",
                "<li><code>/projects/&lt;project&gt;/episodes</code></li>",
                "<li><code>/deliveries/&lt;project&gt;</code></li>",
            ]
        )
        review_link = "/review/projects/example/playlists"

    nav_items.extend(
        [
            '<li><a href="/errors">Reconciliation mismatches</a></li>',
            '<li><a href="/errors/summary">Mismatch summary</a></li>',
            f'<li><a href="{review_link}">Review playlists API</a></li>',
        ]
    )

    template = _load_landing_template()
    projects_json = escape(json.dumps(projects))
    nav_html = "\n        ".join(nav_items)
    html = template.replace("{{PROJECTS_JSON}}", projects_json).replace(
        "{{NAV_ITEMS}}", nav_html
    )
    return HTMLResponse(content=html)


@app.get("/status")
async def status(
    shotgrid_service: ShotGridService = Depends(get_shotgrid_service),
    reconcile_service: ReconcileService = Depends(get_reconcile_service),
    ingest_facade: IngestRunDashboardFacade = Depends(get_ingest_dashboard_facade),
) -> JSONResponse:
    summary = shotgrid_service.overall_status()
    errors = reconcile_service.list_errors()
    ingest_summary = ingest_facade.summarise_recent_runs()
    payload = {**summary, "errors": len(errors), "ingest": ingest_summary}
    return JSONResponse(content=payload)


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
) -> JSONResponse:
    payload = delivery_service.list_deliveries(project_name)
    return JSONResponse(content=payload)
