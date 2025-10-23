"""Deliver approved ShotGrid versions with OnePiece packaging rules."""

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, cast

import structlog
import typer

from apps.onepiece.utils.progress import progress_tracker
from libraries.integrations.aws.s5_sync import s5_sync
from libraries.automation.delivery.manifest import (
    compute_checksum,
    write_csv_manifest,
    write_json_manifest,
)
from libraries.integrations.shotgrid.client import ShotgridClient
from libraries.platform.validations.filesystem import check_paths

log = structlog.get_logger(__name__)

_CONTEXT_CHOICES = ("vendor_out", "client_out")

app = typer.Typer(help="Shotgrid related commands.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_shot_components(shot_code: str) -> tuple[str, str, str, str, str]:
    """Split shot code into 5 components with fallbacks."""
    parts = [part for part in shot_code.split("_") if part]
    defaults = ["unknown"] * 5
    for index, value in enumerate(parts[:5]):
        defaults[index] = value
    return tuple(defaults)  # type: ignore[return-value]


def _parse_version(value: object) -> int:
    """Extract integer version from raw value like 'v003' or 3."""
    if isinstance(value, int):
        return value
    text = str(value).strip().lstrip("vV")
    try:
        return int(text)
    except (TypeError, ValueError):
        log.warning("deliver.invalid_version", value=value)
        return 0


def _validate_files(paths: Iterable[Path]) -> list[Path]:
    """Check existence of files, return list of missing paths."""
    results = check_paths(paths)
    missing = [Path(p) for p, info in results.items() if not info["exists"]]
    for path in missing:
        log.error("deliver.missing_file", path=str(path))
    return missing


def _slugify_project(name: str) -> str:
    """Convert project name into safe slug for S3 keys."""
    slug = name.strip().replace(" ", "_")
    return slug or "project"


def _write_archive_manifest(
    archive: zipfile.ZipFile, metadata: list[dict[str, object]]
) -> None:
    """Write manifest.json and manifest.csv into the archive.

    If metadata has one record, manifest.json will contain a dict.
    If multiple records, manifest.json will contain a list.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        json_path = tmp_dir / "manifest.json"
        csv_path = tmp_dir / "manifest.csv"

        # Always validate metadata by writing to external manifest format
        write_json_manifest(metadata, json_path)
        write_csv_manifest(metadata, csv_path)

        # Prepare test-friendly JSON manifest for the archive
        archive_manifest: dict[str, object] | list[dict[str, object]]
        if len(metadata) == 1:
            archive_manifest = metadata[0]
        else:
            archive_manifest = metadata

        tmp_json_for_archive = tmp_dir / "manifest_for_archive.json"
        with open(tmp_json_for_archive, "w", encoding="utf-8") as fh:
            json.dump(archive_manifest, fh, indent=2)

        archive.write(tmp_json_for_archive, arcname="manifest.json")
        archive.write(csv_path, arcname="manifest.csv")


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@app.command("deliver")
def deliver(
    *,
    project: str = typer.Option(..., "--project", help="ShotGrid project name"),
    episodes: list[str] | None = typer.Option(
        None,
        "--episodes",
        help="Optional episode codes to restrict the delivery",
    ),
    context: str = typer.Option(
        ..., "--context", case_sensitive=False, help="Delivery context"
    ),
    output: Path = typer.Option(..., "--output", help="Path to the output ZIP archive"),
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        help="Optional path where the manifest (JSON + CSV) should be written",
    ),
) -> None:
    """Package approved versions into an archive and upload to S3."""

    normalized_context = context.lower()
    if normalized_context not in _CONTEXT_CHOICES:
        raise typer.BadParameter(
            f"context must be one of: {', '.join(_CONTEXT_CHOICES)}",
            param_hint="--context",
        )

    client = ShotgridClient()
    log.info(
        "deliver.fetch_versions",
        project=project,
        episodes=episodes or [],
        context=normalized_context,
    )

    approved = client.get_approved_versions(project, episodes)
    if not approved:
        typer.echo("No approved versions found for delivery.")
        return

    source_paths = [Path(cast(str, item["file_path"])) for item in approved]
    missing = _validate_files(source_paths)
    if missing:
        raise typer.Exit(code=1)

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    metadata: list[dict[str, object]] = []
    total_versions = len(approved)

    with progress_tracker(
        "ShotGrid Delivery Packaging",
        total=max(total_versions, 1),
        task_description="Collecting approved media",
    ) as packaging_progress:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for record in approved:
                shot_code = record.get("shot", "unknown")
                version_value = record.get("version", 0)
                source = Path(cast(str, record.get("file_path", "")))
                status = record.get("status", "")

                show, episode, scene, shot, asset = _parse_shot_components(
                    str(shot_code)
                )
                version_number = _parse_version(version_value)
                extension = source.suffix or ""

                delivery_name = f"{show}_{episode}_{scene}_{shot}_{asset}_v{version_number:03}{extension}"

                checksum = compute_checksum(source)
                delivery_record = {
                    "show": show,
                    "episode": episode,
                    "scene": scene,
                    "shot": shot,
                    "asset": asset,
                    "version": version_number,
                    "source_path": str(source),
                    "delivery_path": delivery_name,
                    "status": status,
                    "checksum": checksum,
                }
                metadata.append(delivery_record)

                log.info(
                    "deliver.add_to_archive",
                    source=str(source),
                    delivery_name=delivery_name,
                    checksum=checksum,
                )
                archive.write(source, arcname=delivery_name)
                packaging_progress.advance(description=f"Queued {delivery_name}")

            # Handle manifest writing while the archive is open
            if manifest is None:
                _write_archive_manifest(archive, metadata)
            else:
                manifest = manifest.resolve()
                manifest.parent.mkdir(parents=True, exist_ok=True)
                if manifest.suffix:
                    json_path = manifest
                    csv_path = manifest.with_suffix(".csv")
                else:
                    json_path = manifest / "manifest.json"
                    csv_path = manifest / "manifest.csv"
                write_json_manifest(metadata, json_path)
                write_csv_manifest(metadata, csv_path)

        packaging_progress.succeed(
            f"Packaged {total_versions} version(s) for delivery."
        )

    log.info("deliver.archive_created", path=str(output), files=len(metadata))

    upload_paths = [output]
    external_manifest_files: list[Path] = []
    if manifest is not None:
        if manifest.suffix:
            external_manifest_files = [manifest, manifest.with_suffix(".csv")]
        else:
            external_manifest_files = [
                manifest / "manifest.json",
                manifest / "manifest.csv",
            ]
        upload_paths.extend(external_manifest_files)

    with tempfile.TemporaryDirectory() as sync_tmp:
        sync_dir = Path(sync_tmp)
        for path in upload_paths:
            target = sync_dir / path.name
            shutil.copy2(path, target)

        destination = f"s3://{normalized_context}/{_slugify_project(project)}"
        log.info(
            "deliver.upload",
            destination=destination,
            files=[p.name for p in upload_paths],
        )

        with progress_tracker(
            "S3 Delivery Upload",
            total=1,
            task_description="Running s5cmd sync",
        ) as upload_progress:
            events = 0

            def _on_progress(line: str) -> None:
                nonlocal events
                events += 1
                upload_progress.update_total(events + 1)
                description = line if line else "Syncing files"
                upload_progress.advance(description=description)

            s5_sync(sync_dir, destination, progress_callback=_on_progress)

            if events == 0:
                upload_progress.advance(description="Sync completed")

            upload_progress.update_total(max(events, 1))
            upload_progress.succeed(f"Uploaded delivery assets to {destination}.")

    if external_manifest_files:
        typer.echo(
            "Manifest written to: "
            + json.dumps([str(p) for p in external_manifest_files], indent=2)
        )
    typer.echo(f"Delivery archive created at {output}")
