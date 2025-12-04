"""Core logic for the :mod:`libraries` media ingest workflow."""

from __future__ import annotations

import asyncio
import concurrent
import inspect
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence, cast

from libraries.integrations.shotgrid.client import (
    ShotgridClient,
    ShotgridOperationError,
    Version,
)
from .checkpoint import (
    ObjectInspectorProtocol,
    ResumableUploaderProtocol,
    UploadCheckpoint,
    UploadCheckpointStore,
    UploaderProtocol,
)
from .exceptions import (
    FilenameValidationError,
    ShotgridAuthenticationError,
    ShotgridConnectivityError,
    ShotgridSchemaError,
)
from .filenames import parse_media_filename
from .logging_utils import get_logger
from .models import IngestReport, IngestedMedia, MediaInfo

from .manifest import (
    Delivery,
    _build_manifest_index,
    load_delivery_manifest,
)
from .uploaders import (
    Boto3Uploader,
    DEFAULT_UPLOAD_CHUNK_SIZE,
    DEFAULT_UPLOAD_CONCURRENCY,
)
from .workers import apply_worker_tuning, execute_uploads


AUTO_WORKER_BYTES_TARGET = 512 * 1024 * 1024
"""Approximate payload size (in bytes) each worker should handle when auto-tuning."""

AUTO_WORKER_FILES_TARGET = 8
"""Target number of files per worker when auto-tuning based on file counts."""

MAX_DIRECTORY_DEPTH = 32
"""Maximum recursion depth allowed when scanning ingest folders."""


def _normalise_identifier(value: str) -> str:
    """Return a case-insensitive representation of production identifiers."""

    return value.strip().lower()


log = get_logger(__name__)


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
    skipped: bool = False


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
    auto_tune_workers: bool = True
    use_asyncio: bool = False
    resume_enabled: bool = False
    checkpoint_dir: Path | None = None
    checkpoint_threshold_bytes: int = 512 * 1024 * 1024
    upload_chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE
    upload_concurrency: int | None = None
    force_reupload: bool = False

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

        self._configured_max_workers = self.max_workers
        self._resolved_worker_count = self.max_workers
        self._worker_analysis: dict[str, object] = {
            "configured_cap": self._configured_max_workers,
            "resolved_workers": self._resolved_worker_count,
            "total_jobs": 0,
            "total_bytes": 0,
            "largest_job": 0,
            "auto_tuned": False,
        }

        self.auto_tune_workers = _env_flag(
            "INGEST_AUTO_WORKERS", self.auto_tune_workers
        )

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

        if (env_concurrency := os.getenv("INGEST_UPLOAD_CONCURRENCY")) is not None:
            try:
                self.upload_concurrency = int(env_concurrency)
            except ValueError:
                log.warning(
                    "ingest.invalid_upload_concurrency_env",
                    value=env_concurrency,
                    default=self.upload_concurrency,
                )

        checkpoint_dir_env = os.getenv("INGEST_CHECKPOINT_DIR")
        if checkpoint_dir_env:
            self.checkpoint_dir = Path(checkpoint_dir_env)
        elif self.checkpoint_dir is None:
            self.checkpoint_dir = Path(".ingest-checkpoints")

        if self.upload_chunk_size <= 0:
            self.upload_chunk_size = DEFAULT_UPLOAD_CHUNK_SIZE
        if self.checkpoint_threshold_bytes < 0:
            self.checkpoint_threshold_bytes = 0

        if self.upload_concurrency is not None and self.upload_concurrency <= 0:
            log.warning(
                "ingest.invalid_upload_concurrency_value",
                value=self.upload_concurrency,
                default=DEFAULT_UPLOAD_CONCURRENCY,
            )
            self.upload_concurrency = None

        if isinstance(self.uploader, Boto3Uploader):
            self.uploader.configure_transfer(
                upload_chunk_size=self.upload_chunk_size,
                max_concurrency=self.upload_concurrency,
            )

    @property
    def worker_count(self) -> int:
        """Return the concurrency that will be used for uploads."""

        return self._resolved_worker_count

    @property
    def worker_analysis(self) -> Mapping[str, object]:
        """Return details captured while sizing the worker pool."""

        return dict(self._worker_analysis)

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

        self._reset_worker_state()

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

        def _iter_candidates() -> Iterable[Path]:
            if not recursive:
                return sorted(folder.iterdir())

            try:
                root_stat = folder.stat(follow_symlinks=False)
            except OSError as exc:
                log.error(
                    "ingest.folder_stat_failed", folder=str(folder), reason=str(exc)
                )
                return ()

            visited_dirs: set[tuple[int, int]] = {(root_stat.st_dev, root_stat.st_ino)}

            def _walk(current: Path, depth: int) -> Iterable[Path]:
                try:
                    with os.scandir(current) as entries:
                        sorted_entries = sorted(entries, key=lambda entry: entry.name)
                except OSError as exc:
                    log.warning(
                        "ingest.directory_unreadable",
                        directory=str(current),
                        reason=str(exc),
                    )
                    return

                for entry in sorted_entries:
                    path = Path(entry.path)
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        log.warning(
                            "ingest.path_stat_failed", path=str(path), reason=str(exc)
                        )
                        continue

                    if entry.is_symlink() and path.is_dir():
                        log.warning(
                            "ingest.symlink_directory_skipped", directory=str(path)
                        )
                        continue

                    if entry.is_dir(follow_symlinks=False):
                        inode = (stat_result.st_dev, stat_result.st_ino)
                        if inode in visited_dirs:
                            log.warning(
                                "ingest.directory_cycle_skipped", directory=str(path)
                            )
                            continue
                        if depth + 1 >= MAX_DIRECTORY_DEPTH:
                            log.warning(
                                "ingest.max_directory_depth_reached",
                                directory=str(path),
                                depth=depth + 1,
                            )
                            continue

                        visited_dirs.add(inode)
                        yield from _walk(path, depth + 1)
                        continue

                    yield path

            return _walk(folder, 0)

        candidates = _iter_candidates()

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

        apply_worker_tuning(
            self,
            upload_jobs,
            logger=log,  # type: ignore[arg-type]
            bytes_target=AUTO_WORKER_BYTES_TARGET,
            files_target=AUTO_WORKER_FILES_TARGET,
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
        results = execute_uploads(self, upload_jobs, checkpoint_store)

        return self._finalise_ingest(report, results, _notify)

    def _reset_worker_state(self) -> None:
        """Restore worker tracking before analysing a new ingest batch."""

        self.max_workers = self._configured_max_workers
        self._resolved_worker_count = self._configured_max_workers
        self._worker_analysis = {
            "configured_cap": self._configured_max_workers,
            "resolved_workers": self._resolved_worker_count,
            "total_jobs": 0,
            "total_bytes": 0,
            "largest_job": 0,
            "auto_tuned": False,
        }

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
            status = "skipped_existing" if result.skipped else "uploaded"
            notify(result.media.path, status)

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

        skip_upload = False
        if not self.force_reupload:
            metadata = self._inspect_existing_object(job)
            if metadata is not None and self._object_matches(job, metadata):
                skip_upload = True
                log.info(
                    "ingest.skip_existing_object",
                    file=str(job.path),
                    bucket=job.bucket,
                    key=job.key,
                )

        if skip_upload:
            media = IngestedMedia(
                path=job.path,
                bucket=job.bucket,
                key=job.key,
                media_info=job.media_info,
                delivery=job.delivery,
                skipped=True,
            )
            return _UploadResult(media=media, warnings=warnings, skipped=True)

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

    def _inspect_existing_object(self, job: _UploadJob) -> Mapping[str, Any] | None:
        if not isinstance(self.uploader, ObjectInspectorProtocol):
            return None

        inspector = cast(ObjectInspectorProtocol, self.uploader)
        try:
            return inspector.head_object(job.bucket, job.key)
        except Exception as exc:  # pragma: no cover - defensive
            if self._is_missing_object_error(exc):
                return None
            log.warning(
                "ingest.head_object_failed",
                file=str(job.path),
                bucket=job.bucket,
                key=job.key,
                error=str(exc),
            )
            return None

    def _object_matches(self, job: _UploadJob, metadata: Mapping[str, Any]) -> bool:
        expected_checksum = job.delivery.checksum if job.delivery else None
        content_length = metadata.get("ContentLength")
        size_matches = False
        if isinstance(content_length, int):
            size_matches = content_length == job.size
        elif isinstance(content_length, str):
            try:
                size_matches = int(content_length) == job.size
            except ValueError:
                size_matches = False

        if expected_checksum:
            checksum_matches = self._metadata_checksum_matches(
                metadata, expected_checksum
            )
            if not checksum_matches:
                return False
            if content_length is None:
                return True
            return size_matches

        return size_matches

    @staticmethod
    def _metadata_checksum_matches(metadata: Mapping[str, Any], checksum: str) -> bool:
        checksum_normalized = checksum.lower()

        candidates: list[str] = []
        etag = metadata.get("ETag")
        if isinstance(etag, str):
            candidates.append(etag)

        metadata_block = metadata.get("Metadata")
        if isinstance(metadata_block, Mapping):
            for key in ("checksum", "Checksum", "md5", "sha256"):
                value = metadata_block.get(key)
                if isinstance(value, str):
                    candidates.append(value)

        for entry in (
            "ChecksumSHA256",
            "ChecksumSHA1",
            "ChecksumCRC32",
            "ChecksumCRC32C",
            "ChecksumCRC64NVME",
        ):
            value = metadata.get(entry)
            if isinstance(value, str):
                candidates.append(value)

        for candidate in candidates:
            normalized = candidate.strip('"').lower()
            if normalized == checksum_normalized:
                return True

        return False

    @staticmethod
    def _is_missing_object_error(error: Exception) -> bool:
        if isinstance(error, FileNotFoundError):
            return True

        response = getattr(error, "response", None)
        if isinstance(response, Mapping):
            error_payload = response.get("Error")
            if isinstance(error_payload, Mapping):
                code = str(error_payload.get("Code", "")).lower()
                if code in {"404", "nosuchkey", "notfound"}:
                    return True

        status_code = getattr(error, "status_code", None)
        if status_code == 404:
            return True

        return False
