"""CLI entry point for ingesting vendor and client deliveries."""

from pathlib import Path
from typing import Literal, cast

import typer

from apps.onepiece.utils.errors import OnePieceValidationError
from apps.onepiece.utils.progress import progress_tracker
from libraries.ingest import Boto3Uploader, MediaIngestService, UploaderProtocol
from libraries.shotgrid.client import ShotgridClient

app = typer.Typer(help="AWS and S3 integration commands")


class _DryRunUploader:
    """Uploader implementation that only logs operations."""

    def upload(
        self, file_path: Path, bucket: str, key: str
    ) -> None:  # pragma: no cover
        typer.echo(f"[dry-run] Would upload {file_path} -> s3://{bucket}/{key}")


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
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate without uploading to S3"
    ),
) -> None:
    """Validate filenames, copy media to S3, and register Versions in ShotGrid."""

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

    total_files = sum(1 for path in folder.rglob("*") if path.is_file())
    status_messages = {"uploaded": "Uploaded", "skipped": "Skipped"}

    with progress_tracker(
        "Media Ingest",
        total=max(total_files, 1),
        task_description="Validating and uploading media",
    ) as progress:

        def _on_progress(path: Path, status: str) -> None:
            verb = status_messages.get(status, status.title())
            progress.advance(description=f"{verb} {path.name}")

        report = service.ingest_folder(
            folder,
            progress_callback=_on_progress,
        )

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
