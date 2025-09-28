"""Core logic for the :mod:`libraries` media ingest workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Protocol, Tuple, cast

from libraries.shotgrid.client import ShotgridClient
from libraries.validations.naming import (
    validate_episode_name,
    validate_scene_name,
    validate_shot,
    validate_shot_name,
    validate_show_name,
)


class _StructuredLogger:
    """Very small adapter that mimics :func:`structlog.get_logger`."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def info(self, event: str, **kwargs: object) -> None:
        self._logger.info("%s %s", event, kwargs)

    def warning(self, event: str, **kwargs: object) -> None:
        self._logger.warning("%s %s", event, kwargs)


log = _StructuredLogger(logging.getLogger(__name__))


class UploaderProtocol(Protocol):
    """Protocol describing the minimal interface required for uploads."""

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        """Upload *file_path* to ``s3://bucket/key``."""


@dataclass(frozen=True)
class MediaInfo:
    """Metadata parsed from a delivery filename."""

    show_code: str
    episode: str
    scene: str
    shot: str
    descriptor: str
    extension: str

    @property
    def shot_name(self) -> str:
        return f"{self.episode}_{self.scene}_{self.shot}"

    @property
    def version_code(self) -> str:
        """Return a stable code suitable for ShotGrid Version entities."""

        descriptor = f"_{self.descriptor}" if self.descriptor else ""
        return f"{self.shot_name}{descriptor}"


@dataclass
class IngestedMedia:
    """Description of a successfully processed media file."""

    path: Path
    bucket: str
    key: str
    media_info: MediaInfo


@dataclass
class IngestReport:
    """Summary of an ingest run."""

    processed: List[IngestedMedia] = field(default_factory=list)
    invalid: List[Tuple[Path, str]] = field(default_factory=list)

    @property
    def processed_count(self) -> int:
        return len(self.processed)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid)


class FilenameValidationError(ValueError):
    """Raised when a filename does not match the expected convention."""


def parse_media_filename(filename: str) -> MediaInfo:
    """Parse *filename* using the production naming conventions."""

    stem, dot, extension = filename.partition(".")
    if not dot:
        raise FilenameValidationError("File is missing an extension")

    parts = stem.split("_")
    if len(parts) < 5:
        raise FilenameValidationError(
            "Filename must contain show, episode, scene, shot, and descriptor"
        )

    show_code, episode, scene, shot, *descriptor_parts = parts

    if not validate_show_name(show_code):
        raise FilenameValidationError(f"Invalid show code: {show_code}")
    if not validate_episode_name(episode):
        raise FilenameValidationError(f"Invalid episode: {episode}")
    if not validate_scene_name(scene):
        raise FilenameValidationError(f"Invalid scene: {scene}")
    if not validate_shot(shot):
        raise FilenameValidationError(f"Invalid shot: {shot}")

    shot_name = f"{episode}_{scene}_{shot}"
    if not validate_shot_name(shot_name):
        raise FilenameValidationError(f"Invalid shot name: {shot_name}")

    descriptor = "_".join(descriptor_parts)
    if not descriptor:
        raise FilenameValidationError("Descriptor must be provided in the filename")

    return MediaInfo(
        show_code=show_code,
        episode=episode,
        scene=scene,
        shot=shot,
        descriptor=descriptor,
        extension=extension,
    )


@dataclass
class MediaIngestService:
    """High level service that validates, uploads, and registers media."""

    project_name: str
    show_code: str
    source: str
    uploader: UploaderProtocol
    shotgrid: ShotgridClient
    vendor_bucket: str = "vendor_in"
    client_bucket: str = "client_in"
    dry_run: bool = False

    def ingest_folder(
        self,
        folder: Path,
        recursive: bool = True,
        progress_callback: Callable[[Path, str], None] | None = None,
    ) -> IngestReport:
        """Ingest all media files from *folder* and return a summary report."""

        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"Incoming folder does not exist: {folder}")

        report = IngestReport()
        candidates: Iterable[Path]
        if recursive:
            candidates = folder.rglob("*")
        else:
            candidates = folder.iterdir()

        for path in sorted(candidates):
            if not path.is_file():
                continue

            def _notify(status: str) -> None:
                if progress_callback is not None:
                    progress_callback(path, status)

            try:
                media_info = parse_media_filename(path.name)
            except FilenameValidationError as exc:
                log.warning("ingest.invalid_filename", file=str(path), reason=str(exc))
                report.invalid.append((path, str(exc)))
                _notify("skipped")
                continue

            if media_info.show_code != self.show_code:
                reason = (
                    f"Show code '{media_info.show_code}' does not match expected "
                    f"'{self.show_code}'"
                )
                log.warning("ingest.mismatched_show", file=str(path), reason=reason)
                report.invalid.append((path, reason))
                _notify("skipped")
                continue

            bucket = self._resolve_bucket()
            key = f"{self.show_code}/{path.relative_to(folder).as_posix()}"

            log.info(
                "ingest.process_file",
                file=str(path),
                bucket=bucket,
                key=key,
                dry_run=self.dry_run,
            )

            if not self.dry_run:
                self.uploader.upload(path, bucket, key)

            version = self.shotgrid.register_version(
                project_name=self.project_name,
                shot_code=media_info.shot_name,
                file_path=path,
                description=media_info.descriptor,
            )

            log.info(
                "ingest.version_registered",
                version_id=version["id"],
                version_code=version["code"],
                shot=media_info.shot_name,
            )

            report.processed.append(
                IngestedMedia(path=path, bucket=bucket, key=key, media_info=media_info)
            )
            _notify("uploaded")

        return report

    def _resolve_bucket(self) -> str:
        source_normalized = self.source.lower()
        if source_normalized not in {"vendor", "client"}:
            raise ValueError("source must be either 'vendor' or 'client'")
        return (
            self.vendor_bucket if source_normalized == "vendor" else self.client_bucket
        )


class S3ClientProtocol(Protocol):
    """Subset of :mod:`boto3`'s S3 client used for uploads."""

    def upload_file(self, Filename: str, Bucket: str, Key: str) -> None:
        """Upload a local file to S3."""


class Boto3Uploader:
    """Concrete uploader that relies on :mod:`boto3` for S3 transfers."""

    def __init__(self, client: S3ClientProtocol | None = None) -> None:
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - exercised in runtime
                raise RuntimeError(
                    "boto3 is required for S3 uploads. Install it via 'pip install boto3'."
                ) from exc
            boto3_client = boto3.client("s3")
            client = cast(S3ClientProtocol, boto3_client)
        self._client: S3ClientProtocol = client

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        self._client.upload_file(str(file_path), bucket, key)
