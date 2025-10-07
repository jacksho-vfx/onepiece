"""Core logic for the :mod:`libraries` media ingest workflow."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Callable,
    Iterable,
    List,
    Mapping,
    Protocol,
    Sequence,
    Tuple,
    cast,
)

from libraries.shotgrid.client import ShotgridClient, ShotgridOperationError
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

    def error(self, event: str, **kwargs: object) -> None:
        self._logger.error("%s %s", event, kwargs)


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
    delivery: Delivery | None = None


@dataclass
class IngestReport:
    """Summary of an ingest run."""

    processed: List[IngestedMedia] = field(default_factory=list)
    invalid: List[Tuple[Path, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def processed_count(self) -> int:
        return len(self.processed)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid)


class FilenameValidationError(ValueError):
    """Raised when a filename does not match the expected convention."""


class ShotgridAuthenticationError(RuntimeError):
    """Raised when ShotGrid rejects the credentials used for ingest."""


class ShotgridSchemaError(RuntimeError):
    """Raised when ShotGrid rejects the payload due to schema mismatches."""


class ShotgridConnectivityError(RuntimeError):
    """Raised when ShotGrid cannot be reached after retries."""


class DeliveryManifestError(ValueError):
    """Raised when delivery manifest payloads cannot be parsed."""


@dataclass(frozen=True)
class Delivery:
    """Structured metadata describing a delivery manifest entry."""

    show: str
    episode: str
    scene: str
    shot: str
    asset: str
    version: int
    source_path: Path
    delivery_path: Path
    checksum: str | None = None

    @property
    def shot_name(self) -> str:
        return f"{self.episode}_{self.scene}_{self.shot}"


def _normalise_manifest_entry(
    entry: Mapping[str, object],
    *,
    index: int,
    manifest_path: Path,
) -> Delivery:
    normalised: dict[str, object] = {
        str(key).lower(): value for key, value in entry.items()
    }

    def _require(key: str) -> object:
        lowered = key.lower()
        if lowered not in normalised:
            raise DeliveryManifestError(
                f"Manifest entry {index} in '{manifest_path}' is missing '{key}'"
            )
        return normalised[lowered]

    checksum_value = normalised.get("checksum")
    checksum = None if checksum_value in (None, "") else str(checksum_value)

    version_raw = _require("version")
    try:
        version = int(version_raw)
    except (TypeError, ValueError) as exc:
        raise DeliveryManifestError(
            f"Manifest entry {index} in '{manifest_path}' has an invalid version: {version_raw!r}"
        ) from exc

    delivery_path_raw = _require("delivery_path")
    if not delivery_path_raw:
        raise DeliveryManifestError(
            f"Manifest entry {index} in '{manifest_path}' has an empty delivery_path"
        )

    source_path_raw = _require("source_path")
    if not source_path_raw:
        raise DeliveryManifestError(
            f"Manifest entry {index} in '{manifest_path}' has an empty source_path"
        )

    return Delivery(
        show=str(_require("show")),
        episode=str(_require("episode")),
        scene=str(_require("scene")),
        shot=str(_require("shot")),
        asset=str(_require("asset")),
        version=version,
        source_path=Path(str(source_path_raw)),
        delivery_path=Path(str(delivery_path_raw)),
        checksum=checksum,
    )


def _load_manifest_rows(manifest_path: Path) -> list[Mapping[str, object]]:
    suffix = manifest_path.suffix.lower()
    if suffix == ".csv":
        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [
                {key: value for key, value in row.items() if key is not None}
                for row in reader
                if any((value or "").strip() for value in row.values())
            ]

    if suffix == ".json":
        with manifest_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, Mapping):
            if "files" in payload:
                rows = payload["files"]
            elif "deliveries" in payload:
                rows = payload["deliveries"]
            else:
                raise DeliveryManifestError(
                    f"JSON manifest '{manifest_path}' must contain a 'files' or 'deliveries' array"
                )
        else:
            raise DeliveryManifestError(
                f"Unsupported JSON manifest payload in '{manifest_path}': {type(payload).__name__}"
            )

        if not isinstance(rows, list):
            raise DeliveryManifestError(
                f"JSON manifest '{manifest_path}' has an invalid entry collection"
            )

        entries: list[Mapping[str, object]] = []
        for index, item in enumerate(rows):
            if not isinstance(item, Mapping):
                raise DeliveryManifestError(
                    f"Manifest entry {index} in '{manifest_path}' is not an object"
                )
            entries.append(cast(Mapping[str, object], item))
        return entries

    raise DeliveryManifestError(
        f"Unsupported manifest format for '{manifest_path}'. Provide a CSV or JSON manifest."
    )


def load_delivery_manifest(manifest_path: Path) -> list[Delivery]:
    """Return :class:`Delivery` entries parsed from *manifest_path*."""

    if not manifest_path.exists() or not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    rows = _load_manifest_rows(manifest_path)
    deliveries: list[Delivery] = []
    for index, entry in enumerate(rows):
        deliveries.append(
            _normalise_manifest_entry(entry, index=index, manifest_path=manifest_path)
        )
    return deliveries


def _build_manifest_index(deliveries: Sequence[Delivery]) -> dict[str, Delivery]:
    index: dict[str, Delivery] = {}
    for delivery in deliveries:
        relative = delivery.delivery_path.as_posix()
        index.setdefault(relative, delivery)
        index.setdefault(delivery.delivery_path.name, delivery)
    return index


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
        manifest: Sequence[Delivery] | Mapping[str, Delivery] | Path | None = None,
    ) -> IngestReport:
        """Ingest all media files from *folder* and return a summary report."""

        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"Incoming folder does not exist: {folder}")

        manifest_entries: list[Delivery] = []
        if manifest is not None:
            if isinstance(manifest, Path):
                manifest_entries = load_delivery_manifest(manifest)
            elif isinstance(manifest, Mapping):
                manifest_entries = list(manifest.values())
            else:
                manifest_entries = list(manifest)

        manifest_lookup = _build_manifest_index(manifest_entries)

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
                report.warnings.append(f"{path.name}: {exc}")
                _notify("skipped")
                continue

            delivery_entry: Delivery | None = None
            if manifest_lookup:
                relative_key = path.relative_to(folder).as_posix()
                delivery_entry = manifest_lookup.get(relative_key)
                if delivery_entry is None:
                    delivery_entry = manifest_lookup.get(path.name)

                if delivery_entry is None:
                    warning = f"Manifest does not contain metadata for '{path.name}'."
                    log.warning(
                        "ingest.manifest_missing_entry",
                        file=str(path),
                        folder=str(folder),
                    )
                    report.warnings.append(warning)
                else:
                    mismatches: list[str] = []
                    if delivery_entry.show != media_info.show_code:
                        mismatches.append(
                            f"show '{delivery_entry.show}' != '{media_info.show_code}'"
                        )
                    if delivery_entry.episode != media_info.episode:
                        mismatches.append(
                            f"episode '{delivery_entry.episode}' != '{media_info.episode}'"
                        )
                    if delivery_entry.scene != media_info.scene:
                        mismatches.append(
                            f"scene '{delivery_entry.scene}' != '{media_info.scene}'"
                        )
                    if delivery_entry.shot != media_info.shot:
                        mismatches.append(
                            f"shot '{delivery_entry.shot}' != '{media_info.shot}'"
                        )
                    if delivery_entry.delivery_path.name != path.name:
                        mismatches.append(
                            f"filename '{delivery_entry.delivery_path.name}' != '{path.name}'"
                        )

                    if mismatches:
                        reason = (
                            "Manifest metadata does not match filename: "
                            + "; ".join(mismatches)
                        )
                        log.warning(
                            "ingest.manifest_mismatch",
                            file=str(path),
                            reason=reason,
                        )
                        report.invalid.append((path, reason))
                        report.warnings.append(f"{path.name}: {reason}")
                        _notify("skipped")
                        continue

            if media_info.show_code != self.show_code:
                reason = (
                    f"Show code '{media_info.show_code}' does not match expected "
                    f"'{self.show_code}'"
                )
                log.warning("ingest.mismatched_show", file=str(path), reason=reason)
                report.invalid.append((path, reason))
                report.warnings.append(f"{path.name}: {reason}")
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

            if self.dry_run:
                destination = f"s3://{bucket}/{key}"
                report.warnings.append(
                    f"Dry run: would upload {path.name} to {destination}"
                )
            else:
                self.uploader.upload(path, bucket, key)

            if self.dry_run:
                report.warnings.append(
                    f"Dry run: would register ShotGrid Version {media_info.version_code}"
                )
                log.info(
                    "ingest.version_registration_skipped",
                    file=str(path),
                    shot=media_info.shot_name,
                    version_code=media_info.version_code,
                    dry_run=True,
                )
            else:
                try:
                    version = self.shotgrid.register_version(
                        project_name=self.project_name,
                        shot_code=media_info.shot_name,
                        file_path=path,
                        description=media_info.descriptor,
                    )
                except ShotgridAuthenticationError:
                    raise
                except PermissionError as exc:
                    message = (
                        "ShotGrid rejected the provided credentials while registering "
                        f"'{media_info.version_code}'."
                    )
                    log.error(
                        "ingest.shotgrid.auth_failed",
                        file=str(path),
                        shot=media_info.shot_name,
                        reason=str(exc),
                    )
                    raise ShotgridAuthenticationError(
                        f"{message} Check the API key or session token before retrying."
                    ) from exc
                except ValueError as exc:
                    message = (
                        "ShotGrid rejected the version payload for "
                        f"'{media_info.version_code}'."
                    )
                    log.error(
                        "ingest.shotgrid.schema_failed",
                        file=str(path),
                        shot=media_info.shot_name,
                        reason=str(exc),
                    )
                    raise ShotgridSchemaError(
                        f"{message} Confirm the project, shot, and template align with ShotGrid before retrying."
                    ) from exc
                except (ShotgridOperationError, ConnectionError, TimeoutError) as exc:
                    message = (
                        "ShotGrid did not respond while registering "
                        f"'{media_info.version_code}'."
                    )
                    log.error(
                        "ingest.shotgrid.connectivity_failed",
                        file=str(path),
                        shot=media_info.shot_name,
                        reason=str(exc),
                    )
                    raise ShotgridConnectivityError(
                        f"{message} Verify network access and ShotGrid availability, then retry the ingest."
                    ) from exc
                except OSError as exc:
                    message = (
                        "Encountered a network error while contacting ShotGrid for "
                        f"'{media_info.version_code}'."
                    )
                    log.error(
                        "ingest.shotgrid.os_error",
                        file=str(path),
                        shot=media_info.shot_name,
                        reason=str(exc),
                    )
                    raise ShotgridConnectivityError(
                        f"{message} Check VPN or proxy settings and retry once connectivity is restored."
                    ) from exc
                else:
                    log.info(
                        "ingest.version_registered",
                        version_id=version["id"],
                        version_code=version["code"],
                        shot=media_info.shot_name,
                    )

            report.processed.append(
                IngestedMedia(
                    path=path,
                    bucket=bucket,
                    key=key,
                    media_info=media_info,
                    delivery=delivery_entry,
                )
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
