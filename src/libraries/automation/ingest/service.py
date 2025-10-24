"""Core logic for the :mod:`libraries` media ingest workflow."""

from __future__ import annotations

import asyncio
import concurrent.futures
import csv
import hashlib
import inspect
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterable,
    List,
    Mapping,
    Protocol,
    Sequence,
    Tuple,
    cast,
    runtime_checkable,
)

from libraries.integrations.shotgrid.client import (
    ShotgridClient,
    ShotgridOperationError,
    Version,
)
from libraries.platform.validations.naming import (
    validate_episode_name,
    validate_scene_name,
    validate_shot,
    validate_shot_name,
    validate_show_name,
)


def _normalise_identifier(value: str) -> str:
    """Return a case-insensitive representation of production identifiers."""

    return value.strip().lower()


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


@dataclass
class UploadCheckpoint:
    """Persisted state describing progress for a resumable upload."""

    file_path: Path
    bucket: str
    key: str
    file_size: int
    bytes_transferred: int = 0
    parts: list[tuple[int, str]] = field(default_factory=list)
    upload_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "file_path": str(self.file_path),
            "bucket": self.bucket,
            "key": self.key,
            "file_size": self.file_size,
            "bytes_transferred": self.bytes_transferred,
            "parts": [[part, etag] for part, etag in self.parts],
            "upload_id": self.upload_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "UploadCheckpoint":
        parts_payload = payload.get("parts", [])
        parts: list[tuple[int, str]] = []
        for entry in parts_payload:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                part_number = int(entry[0])
                etag = str(entry[1])
                parts.append((part_number, etag))
        return cls(
            file_path=Path(str(payload["file_path"])),
            bucket=str(payload["bucket"]),
            key=str(payload["key"]),
            file_size=int(payload.get("file_size", 0)),
            bytes_transferred=int(payload.get("bytes_transferred", 0)),
            parts=parts,
            upload_id=payload.get("upload_id"),
        )


@runtime_checkable
class ResumableUploaderProtocol(UploaderProtocol, Protocol):
    """Uploader that supports resumable, checkpointed transfers."""

    def upload_resumable(
        self,
        file_path: Path,
        bucket: str,
        key: str,
        checkpoint: UploadCheckpoint,
        chunk_size: int,
        progress_callback: Callable[[UploadCheckpoint], None] | None = None,
    ) -> None:
        """Upload using *checkpoint* state and invoke *progress_callback* per chunk."""


class UploadCheckpointStore:
    """Thread-safe persistence helper for resumable upload checkpoints."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()
        self._directory.mkdir(parents=True, exist_ok=True)

    def load(self, bucket: str, key: str) -> UploadCheckpoint | None:
        path = self._entry_path(bucket, key)
        with self._lock:
            if not path.exists():
                return None
            raw = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("ingest.checkpoint_corrupt", checkpoint=str(path))
            return None
        try:
            return UploadCheckpoint.from_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            log.warning(
                "ingest.checkpoint_invalid",
                checkpoint=str(path),
                error=str(exc),
            )
            return None

    def save(self, checkpoint: UploadCheckpoint) -> None:
        path = self._entry_path(checkpoint.bucket, checkpoint.key)
        payload = checkpoint.to_payload()
        encoded = json.dumps(payload, indent=2, sort_keys=True)
        temp_path = path.with_suffix(".tmp")
        with self._lock:
            temp_path.write_text(encoded, encoding="utf-8")
            temp_path.replace(path)

    def delete(self, bucket: str, key: str) -> None:
        path = self._entry_path(bucket, key)
        with self._lock:
            if path.exists():
                path.unlink()

    def _entry_path(self, bucket: str, key: str) -> Path:
        digest = hashlib.sha1(f"{bucket}:{key}".encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.json"


def _format_shot_name(episode: str, scene: str, shot: str) -> str:
    return f"{episode}_{scene}_{shot}"


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
        return _format_shot_name(self.episode, self.scene, self.shot)

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
        return _format_shot_name(self.episode, self.scene, self.shot)


@dataclass(frozen=True)
class _UploadJob:
    path: Path
    bucket: str
    key: str
    media_info: "MediaInfo"
    delivery: Delivery | None
    size: int


@dataclass(frozen=True)
class _UploadResult:
    media: IngestedMedia
    warnings: list[str]


def _normalise_manifest_entry(
    entry: Mapping[str, object],
    *,
    index: int,
    manifest_path: Path,
) -> Delivery:
    def _normalise_manifest_path(value: object) -> Path:
        """Return a :class:`Path` that treats ``\\`` as directory separators."""

        text = str(value).strip()
        # Delivery manifests may be authored on Windows which means relative
        # paths are delimited by ``\\``.  ``Path`` on POSIX platforms treats
        # those backslashes as literal characters, so convert them to forward
        # slashes before constructing the path.  This keeps manifest lookups
        # consistent regardless of the authoring platform.
        normalised = text.replace("\\", "/")
        return Path(normalised)

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
        version = int(cast(str, version_raw))
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
        source_path=_normalise_manifest_path(source_path_raw),
        delivery_path=_normalise_manifest_path(delivery_path_raw),
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
    max_workers: int = 1
    use_asyncio: bool = False
    resume_enabled: bool = False
    checkpoint_dir: Path | None = None
    checkpoint_threshold_bytes: int = 512 * 1024 * 1024
    upload_chunk_size: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        def _env_flag(name: str, default: bool) -> bool:
            value = os.getenv(name)
            if value is None:
                return default
            return value.lower() in {"1", "true", "yes", "on"}

        self._show_code_normalized = _normalise_identifier(self.show_code)

        if (env_workers := os.getenv("INGEST_MAX_WORKERS")) is not None:
            try:
                self.max_workers = int(env_workers)
            except ValueError:
                log.warning(
                    "ingest.invalid_max_workers_env",
                    value=env_workers,
                    default=self.max_workers,
                )
        self.max_workers = max(1, self.max_workers)

        self.use_asyncio = _env_flag("INGEST_USE_ASYNCIO", self.use_asyncio)
        self.resume_enabled = _env_flag("INGEST_RESUME_ENABLED", self.resume_enabled)

        if (env_threshold := os.getenv("INGEST_CHECKPOINT_THRESHOLD")) is not None:
            try:
                self.checkpoint_threshold_bytes = int(env_threshold)
            except ValueError:
                log.warning(
                    "ingest.invalid_checkpoint_threshold_env",
                    value=env_threshold,
                    default=self.checkpoint_threshold_bytes,
                )

        if (env_chunk := os.getenv("INGEST_UPLOAD_CHUNK_SIZE")) is not None:
            try:
                self.upload_chunk_size = int(env_chunk)
            except ValueError:
                log.warning(
                    "ingest.invalid_chunk_size_env",
                    value=env_chunk,
                    default=self.upload_chunk_size,
                )

        checkpoint_dir_env = os.getenv("INGEST_CHECKPOINT_DIR")
        if checkpoint_dir_env:
            self.checkpoint_dir = Path(checkpoint_dir_env)
        elif self.checkpoint_dir is None:
            self.checkpoint_dir = Path(".ingest-checkpoints")

        if self.upload_chunk_size <= 0:
            self.upload_chunk_size = 64 * 1024 * 1024
        if self.checkpoint_threshold_bytes < 0:
            self.checkpoint_threshold_bytes = 0

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
        matched_manifest_entries: set[Delivery] = set()

        report = IngestReport()
        candidates: Iterable[Path]
        if recursive:
            candidates = folder.rglob("*")
        else:
            candidates = folder.iterdir()

        def _notify(path: Path, status: str) -> None:
            if progress_callback is not None:
                progress_callback(path, status)

        upload_jobs: list[_UploadJob] = []

        for path in sorted(candidates):
            if not path.is_file():
                continue

            try:
                media_info = parse_media_filename(path.name)
            except FilenameValidationError as exc:
                log.warning("ingest.invalid_filename", file=str(path), reason=str(exc))
                report.invalid.append((path, str(exc)))
                report.warnings.append(f"{path.name}: {exc}")
                _notify(path, "skipped")
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
                    matched_manifest_entries.add(delivery_entry)
                    mismatches: list[str] = []
                    if _normalise_identifier(
                        delivery_entry.show
                    ) != _normalise_identifier(media_info.show_code):
                        mismatches.append(
                            f"show '{delivery_entry.show}' != '{media_info.show_code}'"
                        )
                    if _normalise_identifier(
                        delivery_entry.episode
                    ) != _normalise_identifier(media_info.episode):
                        mismatches.append(
                            f"episode '{delivery_entry.episode}' != '{media_info.episode}'"
                        )
                    if _normalise_identifier(
                        delivery_entry.scene
                    ) != _normalise_identifier(media_info.scene):
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
                        _notify(path, "skipped")
                        continue

            if (
                _normalise_identifier(media_info.show_code)
                != self._show_code_normalized
            ):
                reason = (
                    f"Show code '{media_info.show_code}' does not match expected "
                    f"'{self.show_code}'"
                )
                log.warning("ingest.mismatched_show", file=str(path), reason=reason)
                report.invalid.append((path, reason))
                report.warnings.append(f"{path.name}: {reason}")
                _notify(path, "skipped")
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

            size = path.stat().st_size
            upload_jobs.append(
                _UploadJob(
                    path=path,
                    bucket=bucket,
                    key=key,
                    media_info=media_info,
                    delivery=delivery_entry,
                    size=size,
                )
            )

        if manifest_entries:
            unmatched_entries = [
                entry
                for entry in manifest_entries
                if entry not in matched_manifest_entries
            ]
            for entry in unmatched_entries:
                warning = (
                    "Manifest entry for "
                    f"'{entry.delivery_path.as_posix()}' "
                    f"(shot {entry.shot_name}) was not found on disk."
                )
                log.warning(
                    "ingest.manifest_unmatched_entry",
                    delivery_path=str(entry.delivery_path),
                    show=entry.show,
                    episode=entry.episode,
                    scene=entry.scene,
                    shot=entry.shot,
                )
                report.warnings.append(warning)

        if not upload_jobs:
            return report

        if self.dry_run:
            for job in upload_jobs:
                destination = f"s3://{job.bucket}/{job.key}"
                report.warnings.append(
                    f"Dry run: would upload {job.path.name} to {destination}"
                )
                report.warnings.append(
                    f"Dry run: would register ShotGrid Version {job.media_info.version_code}"
                )
                log.info(
                    "ingest.version_registration_skipped",
                    file=str(job.path),
                    shot=job.media_info.shot_name,
                    version_code=job.media_info.version_code,
                    dry_run=True,
                )
                report.processed.append(
                    IngestedMedia(
                        path=job.path,
                        bucket=job.bucket,
                        key=job.key,
                        media_info=job.media_info,
                        delivery=job.delivery,
                    )
                )
                _notify(job.path, "uploaded")
            return report

        checkpoint_store = (
            self._build_checkpoint_store() if self.resume_enabled else None
        )
        results = self._execute_uploads(upload_jobs, checkpoint_store)

        return self._finalise_ingest(report, results, _notify)

    def _resolve_bucket(self) -> str:
        source_normalized = self.source.lower()
        if source_normalized not in {"vendor", "client"}:
            raise ValueError("source must be either 'vendor' or 'client'")
        return (
            self.vendor_bucket if source_normalized == "vendor" else self.client_bucket
        )

    def _build_checkpoint_store(self) -> UploadCheckpointStore:
        if self.checkpoint_dir is None:
            raise RuntimeError(
                "Resume support was enabled without configuring a checkpoint directory"
            )
        return UploadCheckpointStore(self.checkpoint_dir)

    def _execute_uploads(
        self,
        jobs: Sequence[_UploadJob],
        checkpoint_store: UploadCheckpointStore | None,
    ) -> list[_UploadResult] | Awaitable[list[_UploadResult]]:
        if not jobs:
            return []

        if self.use_asyncio:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self._run_asyncio_jobs(jobs, checkpoint_store))
            else:
                return self._run_asyncio_jobs(jobs, checkpoint_store)

        if self.max_workers <= 1:
            return [self._process_job(job, checkpoint_store) for job in jobs]

        results: dict[Path, _UploadResult] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            future_to_job = {
                executor.submit(self._process_job, job, checkpoint_store): job
                for job in jobs
            }
            for future in concurrent.futures.as_completed(future_to_job):
                job = future_to_job[future]
                results[job.path] = future.result()

        return [results[job.path] for job in jobs]

    def _finalise_ingest(
        self,
        report: IngestReport,
        results: list[_UploadResult] | Awaitable[list[_UploadResult]],
        notify: Callable[[Path, str], None],
    ) -> IngestReport:
        resolved_results = self._resolve_upload_results(results)

        for result in resolved_results:
            report.processed.append(result.media)
            report.warnings.extend(result.warnings)
            notify(result.media.path, "uploaded")

        return report

    def _resolve_upload_results(
        self, results: list[_UploadResult] | Awaitable[list[_UploadResult]]
    ) -> list[_UploadResult]:
        if inspect.isawaitable(results):
            return self._await_upload_results(results)
        return list(results)

    def _await_upload_results(
        self, awaitable: Awaitable[list[_UploadResult]]
    ) -> list[_UploadResult]:
        async def _consume() -> list[_UploadResult]:
            return await awaitable

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_consume())

        result: list[_UploadResult] | None = None
        error: BaseException | None = None

        def _runner() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(_consume())
            except BaseException as exc:  # pragma: no cover - defensive
                error = exc

        thread = threading.Thread(
            target=_runner,
            name="MediaIngestAwaitableRunner",
        )
        thread.start()
        thread.join()

        if error is not None:
            raise error
        assert result is not None
        return result

    async def _run_asyncio_jobs(
        self,
        jobs: Sequence[_UploadJob],
        checkpoint_store: UploadCheckpointStore | None,
    ) -> list[_UploadResult]:
        semaphore = asyncio.Semaphore(self.max_workers)

        async def _run(job: _UploadJob) -> _UploadResult:
            async with semaphore:
                return await asyncio.to_thread(self._process_job, job, checkpoint_store)

        return list(await asyncio.gather(*(_run(job) for job in jobs)))

    def _process_job(
        self, job: _UploadJob, checkpoint_store: UploadCheckpointStore | None
    ) -> _UploadResult:
        warnings: list[str] = []
        should_checkpoint = self._should_checkpoint(job, checkpoint_store)

        if should_checkpoint and not isinstance(
            self.uploader, ResumableUploaderProtocol
        ):
            warning = (
                "Resume requested for "
                f"{job.path.name} but the configured uploader does not support resumable transfers."
            )
            warnings.append(warning)
            log.warning(
                "ingest.resume_unsupported",
                file=str(job.path),
                bucket=job.bucket,
                key=job.key,
            )

        self._upload_job(job, checkpoint_store, should_checkpoint)
        version = self._register_version(job)

        media = IngestedMedia(
            path=job.path,
            bucket=job.bucket,
            key=job.key,
            media_info=job.media_info,
            delivery=job.delivery,
        )

        if version is not None:
            log.info(
                "ingest.version_registered",
                version_id=version["id"],
                version_code=version["code"],
                shot=job.media_info.shot_name,
            )

        return _UploadResult(media=media, warnings=warnings)

    def _upload_job(
        self,
        job: _UploadJob,
        checkpoint_store: UploadCheckpointStore | None,
        should_checkpoint: bool,
    ) -> None:
        if should_checkpoint and isinstance(self.uploader, ResumableUploaderProtocol):
            assert checkpoint_store is not None
            resumable = self.uploader
            checkpoint = checkpoint_store.load(job.bucket, job.key)
            if checkpoint is None:
                checkpoint = UploadCheckpoint(
                    file_path=job.path,
                    bucket=job.bucket,
                    key=job.key,
                    file_size=job.size,
                )
            else:
                if (
                    checkpoint.file_size != job.size
                    or checkpoint.bytes_transferred > job.size
                ):
                    log.warning(
                        "ingest.checkpoint_reset",
                        file=str(job.path),
                        bucket=job.bucket,
                        key=job.key,
                        previous_size=checkpoint.file_size,
                        current_size=job.size,
                        transferred=checkpoint.bytes_transferred,
                    )
                    checkpoint.bytes_transferred = 0
                    checkpoint.parts.clear()
                    checkpoint.upload_id = None
                checkpoint.file_path = job.path
                checkpoint.file_size = job.size

            checkpoint_store.save(checkpoint)

            def _persist(state: UploadCheckpoint) -> None:
                checkpoint_store.save(state)

            try:
                resumable.upload_resumable(
                    job.path,
                    job.bucket,
                    job.key,
                    checkpoint,
                    max(self.upload_chunk_size, 1),
                    _persist,
                )
            except Exception:
                checkpoint_store.save(checkpoint)
                raise
            else:
                checkpoint_store.delete(job.bucket, job.key)
            return

        self.uploader.upload(job.path, job.bucket, job.key)
        if should_checkpoint and checkpoint_store is not None:
            checkpoint_store.delete(job.bucket, job.key)

    def _register_version(self, job: _UploadJob) -> Version:
        media_info = job.media_info
        path = job.path
        try:
            return self.shotgrid.register_version(
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

    def _should_checkpoint(
        self, job: _UploadJob, checkpoint_store: UploadCheckpointStore | None
    ) -> bool:
        return (
            self.resume_enabled
            and checkpoint_store is not None
            and job.size >= self.checkpoint_threshold_bytes
        )


class S3ClientProtocol(Protocol):
    """Subset of :mod:`boto3`'s S3 client used for uploads."""

    def upload_file(self, Filename: str, Bucket: str, Key: str) -> None:
        """Upload a local file to S3."""

    def create_multipart_upload(self, Bucket: str, Key: str) -> Mapping[str, Any]:
        """Initiate a multipart upload."""

    def upload_part(
        self,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
    ) -> Mapping[str, Any]:
        """Upload a single multipart chunk."""

    def complete_multipart_upload(
        self,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Finalize a multipart upload."""

    def abort_multipart_upload(self, Bucket: str, Key: str, UploadId: str) -> None:
        """Abort a multipart upload."""


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

    def upload_resumable(
        self,
        file_path: Path,
        bucket: str,
        key: str,
        checkpoint: UploadCheckpoint,
        chunk_size: int,
        progress_callback: Callable[[UploadCheckpoint], None] | None = None,
    ) -> None:
        chunk_size = max(chunk_size, 5 * 1024 * 1024)
        upload_id = checkpoint.upload_id

        if upload_id is None:
            response = self._client.create_multipart_upload(Bucket=bucket, Key=key)
            upload_id = str(response["UploadId"])
            checkpoint.upload_id = upload_id
            if progress_callback is not None:
                progress_callback(checkpoint)

        part_number = len(checkpoint.parts) + 1
        bytes_transferred = checkpoint.bytes_transferred

        with file_path.open("rb") as handle:
            handle.seek(bytes_transferred)
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                response = self._client.upload_part(
                    Bucket=bucket,
                    Key=key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=chunk,
                )
                etag = str(response.get("ETag", ""))
                checkpoint.bytes_transferred += len(chunk)
                checkpoint.parts.append((part_number, etag))
                if progress_callback is not None:
                    progress_callback(checkpoint)
                part_number += 1

        if not checkpoint.parts:
            # Fallback for tiny objects where multipart uploads are unnecessary.
            self.upload(file_path, bucket, key)
            return

        parts_payload = [
            {"ETag": etag, "PartNumber": part_number}
            for part_number, etag in checkpoint.parts
        ]

        self._client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts_payload},
        )
        checkpoint.upload_id = None
        if progress_callback is not None:
            progress_callback(checkpoint)
