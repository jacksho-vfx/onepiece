"""FastAPI dashboard exposing aggregated project status information."""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, Awaitable

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from libraries.delivery.manifest import get_manifest_data
from libraries.reconcile import comparator

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
    ) -> None:
        self._client = client
        self._configured_projects = set(known_projects or [])
        self._fetcher = version_fetcher

    def _filter_versions(self, project_name: str) -> list[Mapping[str, Any]]:
        versions = [
            version
            for version in self._fetch_versions()
            if str(version.get("project")) == project_name
        ]

        if not versions and project_name not in self._configured_projects:
            raise KeyError(project_name)

        return versions

    def _fetch_versions(self) -> list[Mapping[str, Any]]:
        """
        Fetch versions from the configured client or fetcher.
        Supports three strategies:
        - self._fetcher callback
        - client.list_versions()
        - client.get_versions_for_project(name)
        """
        if self._fetcher is not None:
            fetcher: Callable[[Any], Sequence[Mapping[str, Any]]] = self._fetcher
            return list(fetcher(self._client))

        if hasattr(self._client, "list_versions"):
            versions_raw: Any = getattr(self._client, "list_versions")()
            if isinstance(versions_raw, Sequence):
                return [dict(item) for item in versions_raw]
            return []

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
        return all_versions

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


def get_shotgrid_service() -> ShotGridService:
    client = get_shotgrid_client()
    return ShotGridService(client, known_projects=_load_known_projects())


def get_reconcile_service() -> ReconcileService:
    return ReconcileService()


def get_delivery_service() -> DeliveryService:
    return DeliveryService()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


app = FastAPI(title="OnePiece Dashboard", version="1.0.0")
_TEMPLATE_CACHE: str | None = None


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
    projects = sorted(_load_known_projects())
    example_project = projects[0] if projects else None

    nav_items: list[str] = [
        '<li><a href="/status">Project status overview</a></li>',
    ]

    if example_project:
        safe_project = escape(example_project)
        nav_items.extend(
            [
                f'<li><a href="/projects/{safe_project}">Summary for {safe_project}</a></li>',
                f'<li><a href="/projects/{safe_project}/episodes">Episode breakdown for {safe_project}</a></li>',
                f'<li><a href="/deliveries/{safe_project}">Deliveries for {safe_project}</a></li>',
            ]
        )
        review_link = f"/review/projects/{safe_project}/playlists"
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
    render_base_url = os.getenv("ONEPIECE_RENDER_BASE_URL", "http://127.0.0.1:8100")
    render_links = textwrap.dedent(
        f"""
              <li>
                <a href=\"{render_base_url}/farms\" target=\"_blank\" rel=\"noopener\">Render farm catalogue</a>
                <span class=\"hint\">Start via <code>trafalgar web render --port &lt;port&gt;</code>.</span>
              </li>
              <li>
                <a href=\"{render_base_url}/jobs\" target=\"_blank\" rel=\"noopener\">Submit render job</a>
                <span class=\"hint\">Review JSON responses from the render service.</span>
              </li>
        """
    )

    html_template = textwrap.dedent(
        """
        <!DOCTYPE html>
        <html lang=\"en\">
          <head>
            <meta charset=\"utf-8\" />
            <title>OnePiece Dashboard</title>
            <style>
              body { font-family: sans-serif; margin: 2rem; }
              h1 { color: #222; }
              ul { list-style: none; padding: 0; }
              li { margin-bottom: 0.5rem; }
              a { color: #0070f3; text-decoration: none; }
              a:hover { text-decoration: underline; }
              .hint { color: #555; font-size: 0.85rem; margin-left: 0.5rem; }
              .review-section { margin-top: 2rem; }
              .playlist-table { border-collapse: collapse; width: 100%; max-width: 48rem; }
              .playlist-table th, .playlist-table td { border: 1px solid #ccc; padding: 0.5rem; text-align: left; }
              .playlist-table th { background-color: #f6f8fa; }
              .playlist-table .placeholder td { text-align: center; font-style: italic; color: #666; }
              .hidden { display: none; }
            </style>
          </head>
          <body>
            <h1>OnePiece Production Dashboard</h1>
            <p>Select a section:</p>
            <ul>
              <li><a href=\"/status\">Project status overview</a></li>
              <li><a href=\"/errors\">Reconciliation mismatches</a></li>
              <li><a href=\"/deliveries/example\">Example project deliveries</a></li>
        __RENDER_LINKS__
        __REVIEW_LINKS__
            </ul>
        __PLAYLIST_PREVIEW__
          </body>
        </html>
        """
    )

    html = (
        html_template.replace("__RENDER_LINKS__", render_links)
        .replace("__REVIEW_LINKS__", review_links)
        .replace("__PLAYLIST_PREVIEW__", playlist_preview.strip())
    )
    return HTMLResponse(content=html)


@app.get("/status")
async def status(
    shotgrid_service: ShotGridService = Depends(get_shotgrid_service),
    reconcile_service: ReconcileService = Depends(get_reconcile_service),
) -> JSONResponse:
    summary = shotgrid_service.overall_status()
    errors = reconcile_service.list_errors()
    payload = {**summary, "errors": len(errors)}
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
