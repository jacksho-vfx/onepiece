"""Automation helpers for generating consistent Maya playblasts."""

from __future__ import annotations

import datetime as _dt
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Protocol

import structlog

try:  # pragma: no cover - maya is optional in most environments
    import pymel.core as pm
except Exception:  # pragma: no cover - fallback for non-Maya environments
    pm = None  # type: ignore[assignment]

from libraries.creative.dcc.utils import normalize_frame_range, sanitize_token

log = structlog.get_logger(__name__)

_SAFE_FORMAT_CHARS = frozenset(string.ascii_lowercase + string.digits + "_")


class ReviewUploader(Protocol):
    """Minimal interface for pushing playblasts to external review tools."""

    def upload(self, media_path: Path, metadata: Mapping[str, Any]) -> str | None:
        """Upload ``media_path`` with ``metadata`` and return a review identifier."""


@dataclass(slots=True)
class PlayblastRequest:
    """Describe how a playblast should be generated."""

    project: str
    shot: str
    artist: str
    camera: str
    version: int
    output_directory: Path
    sequence: str | None = None
    format: str = "mov"
    codec: str = "h264"
    resolution: tuple[int, int] = (1920, 1080)
    frame_range: tuple[int, int] | None = None
    description: str | None = None
    include_audio: bool = False
    extra_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError("version must be zero or greater")
        if len(self.resolution) != 2:
            raise ValueError("resolution must contain width and height")
        try:
            width = int(self.resolution[0])
            height = int(self.resolution[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("resolution width and height must be integers") from exc
        if width <= 0 or height <= 0:
            raise ValueError("resolution width and height must be greater than zero")
        self.resolution = (width, height)


@dataclass(slots=True)
class PlayblastResult:
    """Summary produced once a playblast has been generated and registered."""

    output_path: Path
    frame_range: tuple[int, int]
    metadata: Mapping[str, Any]
    shotgrid_version: Mapping[str, Any] | None = None
    review_id: str | None = None


def build_playblast_filename(request: PlayblastRequest, timestamp: _dt.datetime) -> str:
    """Return a consistently formatted playblast filename for ``request``."""

    parts: list[str] = [
        sanitize_token(request.project, fallback="UNKNOWN"),
    ]
    if request.sequence:
        parts.append(sanitize_token(request.sequence, fallback="UNKNOWN"))
    parts.extend(
        [
            sanitize_token(request.shot, fallback="UNKNOWN"),
            sanitize_token(request.camera, fallback="UNKNOWN"),
            f"V{request.version:03d}",
            sanitize_token(request.artist, fallback="UNKNOWN"),
            timestamp.strftime("%Y%m%d"),
        ]
    )

    basename = "_".join(filter(None, parts))
    candidate_extension = request.format.strip().lstrip(".").lower()
    if not candidate_extension or any(
        char not in _SAFE_FORMAT_CHARS for char in candidate_extension
    ):
        extension = "mov"
    else:
        extension = candidate_extension
    return f"{basename}.{extension}"


def _default_timeline_query() -> Any:  # pragma: no cover - requires Maya
    if pm is None:
        raise RuntimeError(
            "Maya is not available; supply a frame range or custom timeline query."
        )
    start = pm.playbackOptions(query=True, min=True)
    end = pm.playbackOptions(query=True, max=True)
    return normalize_frame_range((start, end))


def _default_playblast(
    request: PlayblastRequest, target: Path, frame_range: tuple[int, int]
) -> Path:  # pragma: no cover - requires Maya
    if pm is None:
        raise RuntimeError(
            "Maya is not available; provide a custom playblast callback."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    kwargs: MutableMapping[str, Any] = {
        "filename": str(target.with_suffix("")),
        "startTime": frame_range[0],
        "endTime": frame_range[1],
        "forceOverwrite": True,
        "format": request.format,
        "compression": request.codec,
        "widthHeight": request.resolution,
        "offScreen": True,
        "percent": 100,
        "quality": 100,
    }
    if request.include_audio:
        kwargs["sound"] = True

    log.info(
        "maya_playblast_start",
        filename=str(target),
        start=frame_range[0],
        end=frame_range[1],
        resolution=request.resolution,
    )
    reported = pm.playblast(**kwargs)
    if reported:
        reported_path = Path(reported)
        if reported_path != target:
            log.warning(
                "maya_playblast_path_mismatch",
                expected=str(target),
                reported=str(reported_path),
            )
        return reported_path

    log.warning("maya_playblast_missing_path", expected=str(target))
    return target


class PlayblastAutomationTool:
    """Coordinate Maya playblast creation and downstream publishing."""

    def __init__(
        self,
        *,
        timeline_query: Callable[[], tuple[int, int]] | None = None,
        playblast_callback: (
            Callable[[PlayblastRequest, Path, tuple[int, int]], Any] | None
        ) = None,
        clock: Callable[[], _dt.datetime] | None = None,
        shotgrid_client: Any | None = None,
        review_uploader: ReviewUploader | None = None,
    ) -> None:
        self._timeline_query = timeline_query or _default_timeline_query
        self._playblast = playblast_callback or _default_playblast
        self._clock = clock or _dt.datetime.utcnow
        self._shotgrid = shotgrid_client
        self._review = review_uploader

    def _resolve_frame_range(self, request: PlayblastRequest) -> Any:
        if request.frame_range is not None:
            return normalize_frame_range(request.frame_range)
        return normalize_frame_range(self._timeline_query())

    def _ensure_path(self, path_like: Any) -> Path:
        if isinstance(path_like, Path):
            return path_like
        return Path(path_like)

    def _collect_metadata(
        self,
        request: PlayblastRequest,
        frame_range: tuple[int, int],
        timestamp: _dt.datetime,
    ) -> Mapping[str, Any]:
        metadata: dict[str, Any] = {
            "project": request.project,
            "sequence": request.sequence,
            "shot": request.shot,
            "camera": request.camera,
            "artist": request.artist,
            "version": f"V{request.version:03d}",
            "frame_range": {"start": frame_range[0], "end": frame_range[1]},
            "frame_range_label": f"{frame_range[0]}-{frame_range[1]}",
            "generated_at": timestamp.isoformat(timespec="seconds"),
            "resolution": {
                "width": request.resolution[0],
                "height": request.resolution[1],
            },
        }
        metadata.update(dict(request.extra_metadata))
        return metadata

    def execute(self, request: PlayblastRequest) -> PlayblastResult:
        frame_range = self._resolve_frame_range(request)
        timestamp = self._clock()
        filename = build_playblast_filename(request, timestamp)
        output_directory = self._ensure_path(request.output_directory)
        target = output_directory / filename
        target.parent.mkdir(parents=True, exist_ok=True)

        generated = self._playblast(request, target, frame_range)
        if not generated:
            raise RuntimeError(
                "Playblast callback did not return an output path; unable to continue."
            )

        try:
            generated_path = self._ensure_path(generated)
        except TypeError as exc:
            raise RuntimeError(
                "Playblast callback returned an unsupported path value; "
                "expected a string or Path-like object."
            ) from exc

        output_root = output_directory.resolve()
        generated_root = generated_path.resolve()

        try:
            generated_root.relative_to(output_root)
        except ValueError as exc:
            raise RuntimeError(
                "Playblast callback reported an output outside the requested directory."
            ) from exc

        metadata = self._collect_metadata(request, frame_range, timestamp)

        shotgrid_version = None
        if self._shotgrid is not None:
            description = request.description or metadata["frame_range_label"]
            shotgrid_version = self._shotgrid.register_version(
                request.project,
                request.shot,
                generated_path,
                description=description,
            )
            log.info(
                "maya_playblast_registered_shotgrid",
                project=request.project,
                shot=request.shot,
                version=shotgrid_version.get("code") if shotgrid_version else None,
            )

        review_id = None
        if self._review is not None:
            review_id = self._review.upload(generated_path, metadata)
            log.info(
                "maya_playblast_uploaded_review",
                shot=request.shot,
                review_id=review_id,
            )

        log.info(
            "maya_playblast_complete",
            path=str(generated_path),
            frame_start=frame_range[0],
            frame_end=frame_range[1],
        )

        return PlayblastResult(
            output_path=generated_path,
            frame_range=frame_range,
            metadata=metadata,
            shotgrid_version=shotgrid_version,
            review_id=review_id,
        )


__all__ = [
    "PlayblastAutomationTool",
    "PlayblastRequest",
    "PlayblastResult",
    "ReviewUploader",
    "build_playblast_filename",
]
