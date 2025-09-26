"""Top-level Typer application exposing AWS utilities."""

from typing import List, Optional

import typer
from upath import UPath

from src.apps.onepiece.aws.ingest import ingest as ingest_command
from src.apps.onepiece.aws.sync_from import sync_from as sync_from_command
from src.apps.onepiece.aws.sync_to import sync_to as sync_to_command

app = typer.Typer(name="aws", help="AWS and S3 integration commands")


app.command("ingest")(ingest_command)


@app.command("sync-from")
def sync_from(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: str,
    dry_run: bool = False,
    include: Optional[List[str]] = typer.Option(None, "--include"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude"),
) -> None:
    """Sync data from S3 into a local folder."""

    sync_from_command(
        bucket=bucket,
        show_code=show_code,
        folder=folder,
        local_path=UPath(local_path),
        dry_run=dry_run,
        include=include,
        exclude=exclude,
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
) -> None:
    """Sync data from a local folder up to S3."""

    sync_to_command(
        bucket=bucket,
        show_code=show_code,
        folder=folder,
        local_path=UPath(local_path),
        dry_run=dry_run,
        include=include,
        exclude=exclude,
    )


__all__ = ["app"]
