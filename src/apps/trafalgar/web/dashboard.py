"""FastAPI dashboard exposing aggregated project status information."""

import json
import os
import textwrap
from datetime import datetime, timezone
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
        versions = [
            v for v in self._fetch_versions() if str(v.get("project")) == project_name
        ]

        if not versions and project_name not in self._configured_projects:
            raise KeyError(project_name)

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
            "latest_published": latest,
        }


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


@app.get("/", response_class=HTMLResponse)
async def landing_page() -> HTMLResponse:
    known_projects = sorted(_load_known_projects())
    example_project = known_projects[0] if known_projects else None

    if example_project:
        review_links = (
            f"          <li><a href=\"/review/projects/{example_project}/playlists\">Review playlists for {example_project}</a></li>\n"
            f"          <li><a href=\"/review/projects/{example_project}/playlists/{{{{playlist}}}}\">Playlist detail endpoint</a></li>\n"
        )
        playlist_preview_template = textwrap.dedent(
            """
            <section class=\"review-section\">
              <h2>Latest review playlists for <span class=\"project-name\">__PROJECT__</span></h2>
              <p>The table below is populated from the playlist review API.</p>
              <table id=\"playlist-summary\" class=\"playlist-table\">
                <thead>
                  <tr>
                    <th>Playlist</th>
                    <th>Clips</th>
                    <th>Shots</th>
                    <th>Total duration (s)</th>
                  </tr>
                </thead>
                <tbody id=\"playlist-summary-body\">
                  <tr class=\"placeholder\"><td colspan=\"4\">Loading playlists…</td></tr>
                </tbody>
              </table>
              <p id=\"playlist-summary-empty\" class=\"hidden\">No playlists were returned for this project.</p>
            </section>
            <script>
              (function() {
                const project = __PROJECT_JSON__;
                const body = document.getElementById("playlist-summary-body");
                const empty = document.getElementById("playlist-summary-empty");
                if (!body) {
                  return;
                }
                fetch('/review/projects/' + encodeURIComponent(project) + '/playlists').then(function(response) {
                  if (!response.ok) {
                    throw new Error('Request failed');
                  }
                  return response.json();
                }).then(function(data) {
                  while (body.firstChild) {
                    body.removeChild(body.firstChild);
                  }
                  const playlists = (data && Array.isArray(data.playlists)) ? data.playlists : [];
                  if (!playlists.length) {
                    if (empty) {
                      empty.classList.remove('hidden');
                    }
                    return;
                  }
                  playlists.forEach(function(entry) {
                    const row = document.createElement('tr');
                    const nameCell = document.createElement('td');
                    const link = document.createElement('a');
                    link.href = '/review/projects/' + encodeURIComponent(project) + '/playlists/' + encodeURIComponent(entry.name);
                    link.textContent = entry.name;
                    nameCell.appendChild(link);
                    row.appendChild(nameCell);

                    const clipsCell = document.createElement('td');
                    clipsCell.textContent = entry.clips ?? '0';
                    row.appendChild(clipsCell);

                    const shotsCell = document.createElement('td');
                    shotsCell.textContent = entry.shots ?? '0';
                    row.appendChild(shotsCell);

                    const durationCell = document.createElement('td');
                    const duration = typeof entry.duration_seconds === 'number' ? entry.duration_seconds.toFixed(2) : '0.00';
                    durationCell.textContent = duration;
                    row.appendChild(durationCell);

                    body.appendChild(row);
                  });
                }).catch(function(error) {
                  while (body.firstChild) {
                    body.removeChild(body.firstChild);
                  }
                  const row = document.createElement('tr');
                  const cell = document.createElement('td');
                  cell.colSpan = 4;
                  cell.textContent = 'Unable to load playlist data: ' + error.message;
                  row.appendChild(cell);
                  body.appendChild(row);
                });
              })();
            </script>
            """
        )
        playlist_preview = (
            playlist_preview_template
            .replace("__PROJECT__", example_project)
            .replace("__PROJECT_JSON__", json.dumps(example_project))
        )
    else:
        review_links = (
            "          <li><code>/review/projects/&lt;project&gt;/playlists</code></li>\n"
            "          <li><code>/review/projects/&lt;project&gt;/playlists/&lt;name&gt;</code></li>\n"
        )
        playlist_preview = textwrap.dedent(
            """
            <section class=\"review-section\">
              <h2>Review playlists</h2>
              <p>Configure the <code>ONEPIECE_DASHBOARD_PROJECTS</code> environment variable to preview playlist summaries directly on this dashboard.</p>
            </section>
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
        __REVIEW_LINKS__
            </ul>
        __PLAYLIST_PREVIEW__
          </body>
        </html>
        """
    )

    html = (
        html_template
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


@app.get("/errors")
async def errors(
    reconcile_service: ReconcileService = Depends(get_reconcile_service),
) -> JSONResponse:
    mismatches = reconcile_service.list_errors()
    return JSONResponse(content=mismatches)


@app.get("/deliveries/{project_name}")
async def deliveries(
    project_name: str,
    delivery_service: DeliveryService = Depends(get_delivery_service),
) -> JSONResponse:
    payload = delivery_service.list_deliveries(project_name)
    return JSONResponse(content=payload)
