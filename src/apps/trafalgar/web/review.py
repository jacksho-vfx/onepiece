"""FastAPI application exposing playlist review data."""

from typing import Any, Iterable, Mapping

import structlog
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from apps.trafalgar.version import TRAFALGAR_VERSION
from apps.trafalgar.web.security import (
    AuthenticatedPrincipal,
    ROLE_REVIEW_READ,
    create_protected_router,
    require_roles,
)
from libraries.automation.review.dailies import DailiesClip, fetch_playlist_versions
from libraries.integrations.shotgrid.api import ShotGridClient, ShotGridError

logger = structlog.get_logger(__name__)


def get_shotgrid_client() -> ShotGridClient:  # pragma: no cover - runtime wiring
    """Construct a ShotGrid client for playlist queries."""

    return ShotGridClient()


def _extract_playlist_name(record: Mapping[str, Any]) -> str | None:
    """Return a human-readable playlist name for *record* if possible."""

    candidates: Iterable[str | None]

    direct_candidates = (
        record.get("playlist_name"),
        record.get("name"),
        record.get("code"),
    )

    attributes = (
        record.get("attributes")
        if isinstance(record.get("attributes"), Mapping)
        else None
    )
    attribute_candidates = (None, None, None)
    if isinstance(attributes, Mapping):
        attribute_candidates = (
            attributes.get("playlist_name"),
            attributes.get("name"),
            attributes.get("code"),
        )

    candidates = list(direct_candidates) + list(attribute_candidates)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _list_project_playlists(client: Any, project_name: str) -> list[str]:
    """Return playlist names visible to *client* for *project_name*."""

    logger.info("review.list_playlists.start", project=project_name)

    if hasattr(client, "list_playlists"):
        try:
            raw = client.list_playlists(project_name)
        except TypeError:
            raw = client.list_playlists()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "review.list_playlists.failed",
                project=project_name,
                error=str(exc),
            )
            return []

        names = [
            _extract_playlist_name(record)
            for record in raw or []
            if isinstance(record, Mapping)
        ]
        result = sorted(_unique([name for name in names if name]))
        logger.info(
            "review.list_playlists.complete", project=project_name, count=len(result)
        )
        return result

    filters: list[dict[str, Any]] = []
    try:
        project = client.get_project(project_name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "review.list_playlists.project_lookup_failed",
            project=project_name,
            error=str(exc),
        )
        project = None

    if isinstance(project, Mapping) and project.get("id") is not None:
        filters.append({"project.id[$eq]": project.get("id")})
    else:
        filters.append({"project": project_name})

    try:
        records = client._get("Playlist", filters, "id,name,code")  # noqa: SLF001
    except ShotGridError as exc:
        logger.error(
            "review.list_playlists.shotgrid_error", project=project_name, error=str(exc)
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "review.list_playlists.unexpected_failure",
            project=project_name,
            error=str(exc),
        )
        return []

    names = [
        _extract_playlist_name(record)
        for record in records or []
        if isinstance(record, Mapping)
    ]
    result = sorted(_unique([name for name in names if name]))
    logger.info(
        "review.list_playlists.complete", project=project_name, count=len(result)
    )
    return result


def _clip_to_dict(clip: DailiesClip) -> dict[str, Any]:
    return {
        "shot": clip.shot,
        "version": clip.version,
        "source_path": clip.source_path,
        "frame_range": clip.frame_range,
        "user": clip.user,
        "duration_seconds": clip.duration_seconds,
    }


def _summarise_clips(clips: Iterable[DailiesClip]) -> dict[str, Any]:
    clip_list = list(clips)
    shots = {clip.shot for clip in clip_list if clip.shot}
    duration = sum((clip.duration_seconds or 0.0) for clip in clip_list)
    return {
        "clips": len(clip_list),
        "shots": len(shots),
        "duration_seconds": float(duration),
    }


app = FastAPI(title="OnePiece Review API", version=TRAFALGAR_VERSION)
router = create_protected_router()


@router.get("/projects/{project_name}/playlists")  # type: ignore[misc]
def list_playlists(
    project_name: str,
    client: ShotGridClient = Depends(get_shotgrid_client),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_REVIEW_READ)),
) -> JSONResponse:
    try:
        playlists = _list_project_playlists(client, project_name)
    except ShotGridError as exc:
        raise HTTPException(
            status_code=502, detail=f"ShotGrid query failed: {exc}"
        ) from exc

    payload: list[dict[str, Any]] = []
    for name in playlists:
        try:
            clips = fetch_playlist_versions(client, project_name, name)
        except ShotGridError as exc:
            logger.error(
                "review.fetch_playlist_versions_failed",
                project=project_name,
                playlist=name,
                error=str(exc),
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to load playlist '{name}'",
            ) from exc
        summary = _summarise_clips(clips)
        payload.append({"name": name, **summary})

    response = {"project": project_name, "playlists": payload}
    return JSONResponse(content=response)


@router.get("/projects/{project_name}/playlists/{playlist_name}")  # type: ignore[misc]
def playlist_detail(
    project_name: str,
    playlist_name: str,
    client: ShotGridClient = Depends(get_shotgrid_client),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_REVIEW_READ)),
) -> JSONResponse:
    try:
        available = _list_project_playlists(client, project_name)
    except ShotGridError as exc:
        raise HTTPException(
            status_code=502, detail=f"ShotGrid query failed: {exc}"
        ) from exc

    if playlist_name not in available:
        raise HTTPException(status_code=404, detail="Playlist not found")

    try:
        clips = fetch_playlist_versions(client, project_name, playlist_name)
    except ShotGridError as exc:
        logger.error(
            "review.fetch_playlist_versions_failed",
            project=project_name,
            playlist=playlist_name,
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail="ShotGrid query failed") from exc

    summary = _summarise_clips(clips)
    response = {
        "project": project_name,
        "playlist": playlist_name,
        "summary": summary,
        "clips": [_clip_to_dict(clip) for clip in clips],
    }
    return JSONResponse(content=response)


app.include_router(router)
