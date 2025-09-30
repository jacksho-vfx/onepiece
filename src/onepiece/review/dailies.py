"""Generate daily review QuickTimes from ShotGrid Versions."""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import structlog
import typer

from libraries.dailies.manifest import write_manifest
from libraries.media.ffmpeg.wrapper import (
    BurnInMetadata,
    create_concat_file,
    run_ffmpeg_concat,
)
from libraries.shotgrid.api import ShotGridClient, ShotGridError

log = structlog.get_logger(__name__)

app = typer.Typer(name="review", help="Review and editorial commands.")

VERSION_FIELDS = ",".join(
    [
        "code",
        "version_number",
        "sg_status_list",
        "sg_path_to_movie",
        "sg_uploaded_movie",
        "sg_path_to_frames",
        "frame_range",
        "sg_uploaded_movie_frame_count",
        "sg_uploaded_movie_frame_rate",
        "created_at",
    ]
)


@dataclass
class DailiesClip:
    """Represent media and metadata for a dailies clip."""

    shot: str
    version: str
    source_path: str
    frame_range: str
    user: str
    duration_seconds: float | None = None


class NoVersionsFoundError(RuntimeError):
    """Raised when no ShotGrid Versions can be resolved for dailies."""


def get_shotgrid_client() -> ShotGridClient:
    """Factory used to construct a ShotGrid client.

    Kept as a dedicated function so tests can monkeypatch the client creation
    without touching Typer wiring.
    """

    return ShotGridClient()


def _resolve_project_filters(client: ShotGridClient, project_name: str) -> list[dict[str, object]]:
    project = client.get_project(project_name)
    if not project:
        log.warning("dailies.project_not_found", project=project_name)
        return [{"project": project_name}]

    project_id = project.get("id")
    if project_id is None:
        return [{"project": project_name}]
    return [{"project": project_id}]


def _playlist_filters(
    client: ShotGridClient, project_name: str, playlist_name: str
) -> list[dict[str, object]]:
    filters = _resolve_project_filters(client, project_name)
    filters.append({"code": playlist_name})
    return filters


def _extract_source(attributes: dict[str, object]) -> str | None:
    for key in ("sg_path_to_movie", "sg_uploaded_movie", "sg_path_to_frames"):
        candidate = attributes.get(key)
        if candidate:
            if isinstance(candidate, dict):
                url = candidate.get("local_path") or candidate.get("url")
                if url:
                    return str(url)
            else:
                return str(candidate)
    return None


def _extract_user(record: dict[str, object]) -> str:
    relationships = record.get("relationships", {})
    if isinstance(relationships, dict):
        user_data = relationships.get("user", {})
        if isinstance(user_data, dict):
            data = user_data.get("data", {})
            if isinstance(data, dict):
                name = data.get("name") or data.get("code")
                if name:
                    return str(name)
    return ""


def _extract_shot(record: dict[str, object], attributes: dict[str, object]) -> str:
    relationships = record.get("relationships", {})
    if isinstance(relationships, dict):
        entity = relationships.get("entity", {})
        if isinstance(entity, dict):
            data = entity.get("data", {})
            if isinstance(data, dict):
                for key in ("name", "code"):
                    value = data.get(key)
                    if value:
                        return str(value)
    return str(attributes.get("code") or "")


def _extract_duration(attributes: dict[str, object]) -> float | None:
    frame_count = attributes.get("sg_uploaded_movie_frame_count")
    frame_rate = attributes.get("sg_uploaded_movie_frame_rate")
    try:
        if frame_count and frame_rate:
            return float(frame_count) / float(frame_rate)
    except (TypeError, ZeroDivisionError, ValueError):  # pragma: no cover - defensive
        return None
    return None


def _build_clip(record: dict[str, object]) -> DailiesClip | None:
    attributes = record.get("attributes", {})
    if not isinstance(attributes, dict):
        return None

    source = _extract_source(attributes)
    if not source:
        return None

    version_name = str(attributes.get("code") or attributes.get("version_number") or "")
    frame_range = str(attributes.get("frame_range") or "")
    user = _extract_user(record)
    shot = _extract_shot(record, attributes)
    duration = _extract_duration(attributes)

    return DailiesClip(
        shot=shot,
        version=version_name,
        source_path=source,
        frame_range=frame_range,
        user=user,
        duration_seconds=duration,
    )


def _fetch_versions(client: ShotGridClient, filters: list[dict[str, object]]) -> list[DailiesClip]:
    log.debug("dailies.fetch_versions", filters=json.dumps(filters))
    records = client._get("Version", filters, VERSION_FIELDS)  # noqa: SLF001 - private API
    clips: list[DailiesClip] = []
    for record in records:
        clip = _build_clip(record)
        if clip:
            clips.append(clip)
    return clips


def fetch_playlist_versions(
    client: ShotGridClient, project_name: str, playlist_name: str
) -> list[DailiesClip]:
    filters = _playlist_filters(client, project_name, playlist_name)
    log.info(
        "dailies.fetch_playlist_versions", project=project_name, playlist=playlist_name
    )
    playlist = client._get_single(  # noqa: SLF001 - private API
        "Playlist",
        filters,
        "id,name,code,versions",
    )
    if not playlist:
        log.warning(
            "dailies.playlist_not_found", project=project_name, playlist=playlist_name
        )
        return []

    relationships = playlist.get("relationships", {}) if isinstance(playlist, dict) else {}
    versions = []
    if isinstance(relationships, dict):
        data = relationships.get("versions", {})
        if isinstance(data, dict):
            versions = data.get("data", [])  # type: ignore[assignment]
    version_ids: list[int] = []
    for entry in versions or []:
        if isinstance(entry, dict) and entry.get("id") is not None:
            try:
                version_ids.append(int(entry["id"]))
            except (TypeError, ValueError):
                continue
    if not version_ids:
        return []

    filters = [{"id[$in]": ",".join(str(vid) for vid in version_ids)}]
    return _fetch_versions(client, filters)


def fetch_today_approved_versions(
    client: ShotGridClient,
    project_name: str,
    now: _dt.datetime | None = None,
) -> list[DailiesClip]:
    now = now or _dt.datetime.now(tz=_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    day_start = now.astimezone(_dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    day_end = day_start + _dt.timedelta(days=1)

    filters = _resolve_project_filters(client, project_name)
    filters.extend(
        [
            {"sg_status_list": "apr"},
            {"created_at[$gte]": day_start.isoformat()},
            {"created_at[$lt]": day_end.isoformat()},
        ]
    )
    log.info(
        "dailies.fetch_today_approved_versions",
        project=project_name,
        start=day_start.isoformat(),
        end=day_end.isoformat(),
    )
    return _fetch_versions(client, filters)


def _build_burnin_metadata(clips: Iterable[DailiesClip]) -> list[BurnInMetadata]:
    return [
        BurnInMetadata(
            shot=clip.shot,
            version=clip.version,
            frame_range=clip.frame_range,
            user=clip.user,
        )
        for clip in clips
    ]


def _render_dailies(
    clips: Sequence[DailiesClip],
    output: Path,
    codec: str,
    burnin: bool,
) -> None:
    sources = [clip.source_path for clip in clips]
    if not sources:
        raise NoVersionsFoundError("No versions resolved after filtering.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        concat_path = create_concat_file(sources, Path(tmp_dir))
        burnin_metadata = _build_burnin_metadata(clips) if burnin else None
        run_ffmpeg_concat(concat_path, output, codec=codec, burnins=burnin_metadata)


def _summarize_duration(clips: Sequence[DailiesClip]) -> float:
    return float(sum(clip.duration_seconds or 0.0 for clip in clips))


@app.command("dailies")
def create_dailies(
    project: str = typer.Option(..., "--project", help="ShotGrid project name"),
    playlist: str | None = typer.Option(
        None, "--playlist", help="ShotGrid playlist name"
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        dir_okay=False,
        resolve_path=True,
        help="Destination QuickTime path.",
    ),
    burnin: bool = typer.Option(
        True,
        "--burnin/--no-burnin",
        help="Overlay shot metadata as text burn-ins.",
    ),
    codec: str = typer.Option(
        "prores", "--codec", help="Output codec passed to ffmpeg (e.g. prores, h264)."
    ),
) -> None:
    """Compile daily review media into a single QuickTime file."""

    log.info(
        "dailies.start",
        project=project,
        playlist=playlist,
        output=str(output),
        burnin=burnin,
        codec=codec,
    )

    client = get_shotgrid_client()

    try:
        if playlist:
            clips = fetch_playlist_versions(client, project, playlist)
        else:
            clips = fetch_today_approved_versions(client, project)
    except ShotGridError as exc:
        log.error("dailies.shotgrid_error", error=str(exc))
        typer.secho(f"ShotGrid query failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not clips:
        log.warning("dailies.no_versions", project=project, playlist=playlist)
        typer.secho("No versions found for the requested parameters.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    with typer.progressbar(clips, label="Processing versions") as progress:
        processed: list[DailiesClip] = []
        for clip in progress:
            processed.append(clip)

    try:
        _render_dailies(processed, output=output, codec=codec, burnin=burnin)
    except NoVersionsFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW)
        raise typer.Exit(code=1) from exc
    except subprocess.CalledProcessError as exc:
        log.error("dailies.ffmpeg_failed", returncode=exc.returncode, stderr=exc.stderr)
        typer.secho("FFmpeg failed to render the dailies output.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    manifest_path = write_manifest(output, processed, codec=codec)
    total_duration = _summarize_duration(processed)

    typer.echo(
        f"Compiled {len(processed)} clips "
        f"({total_duration:.2f}s) into {output}"
    )
    typer.echo(f"Manifest: {manifest_path}")

    log.info(
        "dailies.completed",
        project=project,
        playlist=playlist,
        output=str(output),
        manifest=str(manifest_path),
        clips=len(processed),
        duration=total_duration,
    )
