"""CLI entry point for ingesting vendor and client deliveries."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, cast

import typer

from apps.onepiece.utils.errors import (
    OnePieceConfigError,
    OnePieceExternalServiceError,
    OnePieceValidationError,
)
from apps.onepiece.utils.progress import progress_tracker
from libraries.ingest import (
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
from libraries.shotgrid.client import ShotgridClient

app = typer.Typer(help="AWS and S3 integration commands")


class _DryRunUploader:
    """Uploader implementation that only logs operations."""

    def upload(
        self, file_path: Path, bucket: str, key: str
    ) -> None:  # pragma: no cover
        typer.echo(f"[dry-run] Would upload {file_path} -> s3://{bucket}/{key}")


ReportFormat = Literal["json", "csv"]


@app.command("ingest")
def ingest(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    project: str = typer.Option(..., "--project", "-p", help="ShotGrid project name"),
    show_code: str = typer.Option(
        ..., "--show-code", "-s", help="Show code used in filenames"
    ),
    source: Literal["vendor", "client"] = typer.Option(
        "vendor",
        "--source",
        help="Delivery source. Determines whether vendor_in or client_in bucket is used.",
    ),
    vendor_bucket: str = typer.Option(
        "vendor_in", help="S3 bucket for vendor deliveries"
    ),
    client_bucket: str = typer.Option(
        "client_in", help="S3 bucket for client deliveries"
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
                param_name="manifest",
            )
        try:
            manifest_entries = load_delivery_manifest(manifest)
        except FileNotFoundError:
            raise typer.BadParameter(
                "Manifest path must point to an existing file",
                param_name="manifest",
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
        project_name=project,
        show_code=show_code,
        source=source,
        uploader=typed_uploader,
        shotgrid=shotgrid,
        vendor_bucket=vendor_bucket,
        client_bucket=client_bucket,
        dry_run=dry_run,
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
