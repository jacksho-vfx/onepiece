"""Top-level Typer application exposing AWS utilities."""

from pathlib import Path
from typing import List, Optional

import typer

from apps.onepiece.aws.ingest import app as ingest
from apps.onepiece.aws.sync_from import sync_from as sync_from_command
from apps.onepiece.aws.sync_to import sync_to as sync_to_command

app = typer.Typer(name="aws", help="AWS and S3 integration commands")
app.add_typer(ingest)


@app.command("sync-from")
def sync_from(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: str,
    dry_run: bool = False,
    include: Optional[List[str]] = typer.Option(None, "--include"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help=(
            "Name of the AWS credential profile to use when running s5cmd "
            "(sets AWS_PROFILE for the sync)."
        ),
    ),
) -> None:
    """Sync data from S3 into a local folder."""

    sync_from_command(
        bucket=bucket,
        show_code=show_code,
        folder=folder,
        local_path=Path(local_path),
        dry_run=dry_run,
        include=include,
        exclude=exclude,
        profile=profile,
    )


@app.command("sync-to")
def sync_to(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: str,
    dry_run: bool = False,
    include: Optional[List[str]] = typer.Option(None, "--include"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help=(
            "Name of the AWS credential profile to use when running s5cmd "
            "(sets AWS_PROFILE for the sync)."
        ),
    ),
) -> None:
    """Sync data from a local folder up to S3."""

    sync_to_command(
        bucket=bucket,
        show_code=show_code,
        folder=folder,
        local_path=Path(local_path),
        dry_run=dry_run,
        include=include,
        exclude=exclude,
        profile=profile,
    )


__all__ = [
    "app",
    "ingest",
    "sync_from",
    "sync_to",
]
