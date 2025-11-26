"""FastAPI dashboard exposing aggregated project status information."""

import json
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import quote

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from apps.trafalgar.version import TRAFALGAR_VERSION
from apps.web_theme import get_theme_static_directory
from ..ingest_adapter import (
    IngestRunDashboardFacade,
    get_ingest_dashboard_facade,
)
from .auth import _bearer_scheme, require_dashboard_auth
from .facades.delivery_service import DeliveryService
from .facades.project_registry import (
    _load_cache_configuration,
    _load_known_projects,
    _load_project_registry,
    _parse_float,
    _parse_int,
)
from .facades.render import RenderDashboardFacade, get_render_dashboard_facade
from .facades.reconcile_service import ReconcileService
from .facades.review import ReviewDashboardFacade, get_review_dashboard_facade
from .facades.shotgrid_service import ShotGridService

logger = structlog.get_logger(__name__)


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
    try:  # pragma: no cover - FastAPI app may not be initialised
        state = getattr(app, "state", None)
    except NameError:  # pragma: no cover - app not yet defined
        state = None
    cache_ttl, cache_max_records, cache_max_projects = _load_cache_configuration(
        state=state
    )
    return ShotGridService(
        client,
        known_projects=_load_known_projects(),
        cache_ttl=cache_ttl,
        cache_max_records=cache_max_records,
        cache_max_projects=cache_max_projects,
        state=state,
    )


def get_reconcile_service() -> ReconcileService:
    try:
        return ReconcileService()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_delivery_service() -> DeliveryService:
    return DeliveryService()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


app = FastAPI(title="OnePiece Dashboard", version=TRAFALGAR_VERSION)
_TEMPLATE_CACHE: str | None = None
_THEME_STATIC_DIR = get_theme_static_directory()
_DASHBOARD_STATIC_DIR = Path(__file__).parent / "static"
app.mount(
    "/theme",
    StaticFiles(directory=_THEME_STATIC_DIR),
    name="trafalgar-shared-theme",
)
app.mount(
    "/dashboard/static",
    StaticFiles(directory=_DASHBOARD_STATIC_DIR),
    name="trafalgar-dashboard-static",
)


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
