"""CLI entry point for ingesting vendor and client deliveries."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Mapping, cast

import typer

from apps.onepiece.config import load_profile
from apps.onepiece.utils.errors import (
    OnePieceConfigError,
    OnePieceExternalServiceError,
    OnePieceValidationError,
)
from apps.onepiece.utils.progress import progress_tracker
from libraries.automation.ingest import (
    Boto3Uploader,
    Delivery,
    DeliveryManifestError,
    IngestReport,
    MediaIngestService,
    ShotgridAuthenticationError,
    ShotgridConnectivityError,
    ShotgridSchemaError,
    UploaderProtocol,
    load_delivery_manifest,
)
from libraries.integrations.shotgrid.client import ShotgridClient

app = typer.Typer(help="AWS and S3 integration commands")


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _validate_source_option(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in {"vendor", "client"}:
        raise typer.BadParameter("--source must be either 'vendor' or 'client'")
    return value


class _DryRunUploader:
    """Uploader implementation that only logs operations."""

    def upload(
        self, file_path: Path, bucket: str, key: str
    ) -> None:  # pragma: no cover
        typer.echo(f"[dry-run] Would upload {file_path} -> s3://{bucket}/{key}")


@dataclass
class _IngestResolvedOptions:
    project: str
    show_code: str
    source: Literal["vendor", "client"]
    vendor_bucket: str
    client_bucket: str
    max_workers: int
    use_asyncio: bool
    resume: bool
    checkpoint_dir: Path
    checkpoint_threshold: int
    upload_chunk_size: int


def _prepare_ingest_options(
    profile_data: Mapping[str, Any],
    *,
    project: str | None,
    show_code: str | None,
    source: str | None,
    vendor_bucket: str | None,
    client_bucket: str | None,
    max_workers: int | None,
    use_asyncio: bool | None,
    resume: bool | None,
    checkpoint_dir: Path | None,
    checkpoint_threshold: int | None,
    upload_chunk_size: int | None,
) -> _IngestResolvedOptions:
    ingest_overrides = profile_data.get("ingest", {})
    if ingest_overrides and not isinstance(ingest_overrides, Mapping):
        raise OnePieceConfigError(
            "Profile 'ingest' configuration must be provided as a table of key/value pairs"
        )

    ingest_mapping: Mapping[str, Any] = cast(Mapping[str, Any], ingest_overrides)

    resolved_project = project or _optional_str(profile_data.get("project"), "project")
    if not resolved_project:
        raise OnePieceConfigError(
            "A ShotGrid project name must be supplied via --project or the selected profile."
        )

    resolved_show_code = show_code or _optional_str(
        profile_data.get("show_code"), "show_code"
    )
    if not resolved_show_code:
        raise OnePieceConfigError(
            "A show code must be supplied via --show-code or the selected profile."
        )

    resolved_source = (
        source or _optional_str(profile_data.get("source"), "source") or "vendor"
    )
    if resolved_source not in {"vendor", "client"}:
        raise OnePieceConfigError(
            "Ingest profile 'source' must be either 'vendor' or 'client'."
        )

    resolved_vendor_bucket = (
        vendor_bucket
        or _optional_str(profile_data.get("vendor_bucket"), "vendor_bucket")
        or "vendor_in"
    )

    resolved_client_bucket = (
        client_bucket
        or _optional_str(profile_data.get("client_bucket"), "client_bucket")
        or "client_in"
    )

    resolved_max_workers = (
        max_workers
        if max_workers is not None
        else _optional_int(ingest_mapping.get("max_workers"), "ingest.max_workers")
    )
    if resolved_max_workers is None:
        resolved_max_workers = int(os.getenv("INGEST_MAX_WORKERS", "4"))

    resolved_use_asyncio = (
        use_asyncio
        if use_asyncio is not None
        else _optional_bool(ingest_mapping.get("use_asyncio"), "ingest.use_asyncio")
    )
    if resolved_use_asyncio is None:
        resolved_use_asyncio = _env_flag("INGEST_USE_ASYNCIO", False)

    resolved_resume = (
        resume
        if resume is not None
        else _optional_bool(ingest_mapping.get("resume"), "ingest.resume")
    )
    if resolved_resume is None:
        resolved_resume = _env_flag("INGEST_RESUME_ENABLED", False)

    resolved_checkpoint_dir = checkpoint_dir or _optional_path(
        ingest_mapping.get("checkpoint_dir"), "ingest.checkpoint_dir"
    )
    if resolved_checkpoint_dir is None:
        resolved_checkpoint_dir = Path(
            os.getenv("INGEST_CHECKPOINT_DIR", ".ingest-checkpoints")
        )

    resolved_checkpoint_threshold = (
        checkpoint_threshold
        if checkpoint_threshold is not None
        else _optional_int(
            ingest_mapping.get("checkpoint_threshold"), "ingest.checkpoint_threshold"
        )
    )
    if resolved_checkpoint_threshold is None:
        resolved_checkpoint_threshold = int(
            os.getenv("INGEST_CHECKPOINT_THRESHOLD", str(512 * 1024 * 1024))
        )

    resolved_upload_chunk_size = (
        upload_chunk_size
        if upload_chunk_size is not None
        else _optional_int(
            ingest_mapping.get("upload_chunk_size"), "ingest.upload_chunk_size"
        )
    )
    if resolved_upload_chunk_size is None:
        resolved_upload_chunk_size = int(
            os.getenv("INGEST_UPLOAD_CHUNK_SIZE", str(64 * 1024 * 1024))
        )

    return _IngestResolvedOptions(
        project=resolved_project,
        show_code=resolved_show_code,
        source=cast(Literal["vendor", "client"], resolved_source),
        vendor_bucket=resolved_vendor_bucket,
        client_bucket=resolved_client_bucket,
        max_workers=resolved_max_workers,
        use_asyncio=resolved_use_asyncio,
        resume=resolved_resume,
        checkpoint_dir=resolved_checkpoint_dir,
        checkpoint_threshold=resolved_checkpoint_threshold,
        upload_chunk_size=resolved_upload_chunk_size,
    )


def _optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise OnePieceConfigError(f"Configuration value '{field}' must be a string.")


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise OnePieceConfigError(f"Configuration value '{field}' must be a boolean.")


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise OnePieceConfigError(f"Configuration value '{field}' must be an integer.")
    if isinstance(value, int):
        return value
    raise OnePieceConfigError(f"Configuration value '{field}' must be an integer.")


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        return Path(value)
    raise OnePieceConfigError(
        f"Configuration value '{field}' must be a filesystem path represented as a string."
    )


ReportFormat = Literal["json", "csv"]


@app.command("ingest")
def ingest(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    project: str | None = typer.Option(
        None, "--project", "-p", help="ShotGrid project name"
    ),
    show_code: str | None = typer.Option(
        None, "--show-code", "-s", help="Show code used in filenames"
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Configuration profile to load from onepiece.toml files.",
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        callback=_validate_source_option,
        help="Delivery source. Determines whether vendor_in or client_in bucket is used.",
    ),
    vendor_bucket: str | None = typer.Option(
        None, "--vendor-bucket", help="S3 bucket for vendor deliveries"
    ),
    client_bucket: str | None = typer.Option(
        None, "--client-bucket", help="S3 bucket for client deliveries"
    ),
    max_workers: int | None = typer.Option(
        None,
        "--max-workers",
        help="Maximum number of concurrent uploads when using worker pools.",
    ),
    use_asyncio: bool | None = typer.Option(
        None,
        "--use-asyncio/--no-use-asyncio",
        help="Coordinate uploads with asyncio instead of thread pools.",
    ),
    resume: bool | None = typer.Option(
        None,
        "--resume/--no-resume",
        help=(
            "Enable resumable uploads with checkpoint persistence for large media files."
        ),
    ),
    checkpoint_dir: Path | None = typer.Option(
        None,
        "--checkpoint-dir",
        help="Directory used to store upload checkpoint metadata when --resume is active.",
    ),
    checkpoint_threshold: int | None = typer.Option(
        None,
        "--checkpoint-threshold",
        help="Minimum file size in bytes that triggers checkpointed uploads.",
    ),
    upload_chunk_size: int | None = typer.Option(
        None,
        "--upload-chunk-size",
        help="Chunk size in bytes used for resumable uploads.",
    ),
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        help=(
            "Optional CSV or JSON manifest describing each delivery entry. "
            "When provided, entries are matched to filenames to enrich ingest metadata."
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate without uploading to S3"
    ),
    report_format: ReportFormat | None = typer.Option(
        None,
        "--report-format",
        help="When using --dry-run, choose whether analytics are exported as JSON or CSV.",
    ),
    report_path: Path | None = typer.Option(
        None,
        "--report-path",
        help="Optional destination file for the analytics report. Defaults to stdout if omitted.",
    ),
) -> None:
    """Validate filenames, copy media to S3, and register Versions in ShotGrid."""

    if report_path is not None and report_format is None:
        raise typer.BadParameter("--report-format is required when using --report-path")

    if (report_format is not None or report_path is not None) and not dry_run:
        raise typer.BadParameter(
            "Analytics reports are only available when --dry-run is used"
        )

    profile_context = load_profile(profile=profile, workspace=folder)
    resolved = _prepare_ingest_options(
        profile_context.data,
        project=project,
        show_code=show_code,
        source=source,
        vendor_bucket=vendor_bucket,
        client_bucket=client_bucket,
        max_workers=max_workers,
        use_asyncio=use_asyncio,
        resume=resume,
        checkpoint_dir=checkpoint_dir,
        checkpoint_threshold=checkpoint_threshold,
        upload_chunk_size=upload_chunk_size,
    )

    total_files = sum(1 for path in folder.rglob("*") if path.is_file())

    if total_files == 0:
        raise OnePieceValidationError(
            "No media files were discovered in the delivery folder. "
            "Run the ingest command with --dry-run to generate a validation "
            "report, share it with the vendor, and retry once files are available."
        )

    manifest_entries: list[Delivery] | None = None
    if manifest is not None:
        if not manifest.exists() or not manifest.is_file():
            raise typer.BadParameter(
                "Manifest path must point to an existing file",
                param_hint="manifest",
            )
        try:
            manifest_entries = load_delivery_manifest(manifest)
        except FileNotFoundError:
            raise typer.BadParameter(
                "Manifest path must point to an existing file",
                param_hint="manifest",
            ) from None
        except DeliveryManifestError as exc:
            raise OnePieceValidationError(
                f"Unable to parse manifest '{manifest}': {exc}. "
                "Update the schema and retry the ingest."
            ) from exc

        if not manifest_entries:
            raise OnePieceValidationError(
                f"Manifest '{manifest}' does not contain any deliveries. Provide at least one entry."
            )

    shotgrid = ShotgridClient()
    uploader = _DryRunUploader() if dry_run else Boto3Uploader()
    typed_uploader: UploaderProtocol = cast(UploaderProtocol, uploader)

    service = MediaIngestService(
        project_name=resolved.project,
        show_code=resolved.show_code,
        source=resolved.source,
        uploader=typed_uploader,
        shotgrid=shotgrid,
        vendor_bucket=resolved.vendor_bucket,
        client_bucket=resolved.client_bucket,
        dry_run=dry_run,
        max_workers=resolved.max_workers,
        use_asyncio=resolved.use_asyncio,
        resume_enabled=resolved.resume,
        checkpoint_dir=resolved.checkpoint_dir,
        checkpoint_threshold_bytes=resolved.checkpoint_threshold,
        upload_chunk_size=resolved.upload_chunk_size,
    )
    status_messages = {"uploaded": "Uploaded", "skipped": "Skipped"}

    with progress_tracker(
        "Media Ingest",
        total=max(total_files, 1),
        task_description="Validating and uploading media",
    ) as progress:

        def _on_progress(path: Path, status: str) -> None:
            verb = status_messages.get(status, status.title())
            progress.advance(description=f"{verb} {path.name}")

        try:
            report = service.ingest_folder(
                folder,
                progress_callback=_on_progress,
                manifest=manifest_entries,
            )
        except ShotgridAuthenticationError as exc:
            raise OnePieceConfigError(
                f"{exc} Verify the ShotGrid credentials configured for ingest, then retry the command."
            ) from exc
        except ShotgridSchemaError as exc:
            raise OnePieceValidationError(
                f"{exc} Update the naming or ShotGrid entities to match, then retry the ingest."
            ) from exc
        except ShotgridConnectivityError as exc:
            raise OnePieceExternalServiceError(
                f"{exc} Check connectivity or service status, then retry the ingest once ShotGrid is reachable."
            ) from exc

        progress.succeed(
            f"Processed {report.processed_count} file(s); {report.invalid_count} skipped."
        )

    for processed in report.processed:
        typer.echo(
            f"Uploaded {processed.path.name} -> s3://{processed.bucket}/{processed.key}"
        )

    if report.invalid:
        typer.echo("\nSkipped files:")
        for path, reason in report.invalid:
            typer.echo(f"- {path.name}: {reason}")

    typer.echo(
        f"\nIngest complete: {report.processed_count} processed, "
        f"{report.invalid_count} skipped"
    )

    if report.processed_count == 0:
        raise OnePieceValidationError(
            "No files were ingested. Provide media that passes validation."
        )

    if dry_run and report_format is not None:
        analytics = _build_dry_run_report(report)
        rendered = _render_report(analytics, report_format)

        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(rendered)
            typer.echo(f"\nDry-run report written to {report_path}")
        else:
            typer.echo("\nDry-run report:")
            typer.echo(rendered)


def _build_dry_run_report(report: IngestReport) -> Dict[str, Any]:
    """Convert *report* into a structure that can be serialised for analytics."""

    processed: Iterable[Dict[str, Any]] = (
        {
            "file": str(entry.path),
            "destination": f"s3://{entry.bucket}/{entry.key}",
            "shot": entry.media_info.shot_name,
            "descriptor": entry.media_info.descriptor,
        }
        for entry in report.processed
    )

    invalid: Iterable[Dict[str, str]] = (
        {"file": str(path), "reason": reason} for path, reason in report.invalid
    )

    warnings: Iterable[str] = tuple(report.warnings)

    return {
        "processed": list(processed),
        "invalid": list(invalid),
        "warnings": list(warnings),
    }


def _render_report(analytics: Dict[str, Any], format: ReportFormat) -> str:
    """Serialise *analytics* into either JSON or CSV."""

    if format == "json":
        return json.dumps(analytics, indent=2, sort_keys=True)

    rows = list(_iter_csv_rows(analytics))
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=["status", "file", "destination", "details"]
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().strip()


def _iter_csv_rows(analytics: Dict[str, Any]) -> Iterable[Dict[str, str]]:
    """Yield CSV rows for processed files, invalid files, and warnings."""

    for item in analytics.get("processed", []):
        destination = cast(str, item.get("destination", ""))
        yield {
            "status": "processed",
            "file": cast(str, item.get("file", "")),
            "destination": destination,
            "details": "",
        }

    for item in analytics.get("invalid", []):
        yield {
            "status": "invalid",
            "file": cast(str, item.get("file", "")),
            "destination": "",
            "details": cast(str, item.get("reason", "")),
        }

    for warning in analytics.get("warnings", []):
        yield {
            "status": "warning",
            "file": "",
            "destination": "",
            "details": cast(str, warning),
        }
