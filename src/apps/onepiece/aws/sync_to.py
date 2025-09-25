from pathlib import Path

import typer

from src.libraries.aws.s5_sync import s5_sync

app = typer.Typer(help="Sync to an S3 bucket")


@app.command("sync-to")
def sync_to(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: Path,
    dry_run: bool = False,
    include: list[str] = typer.Option(None, "--include"),
    exclude: list[str] = typer.Option(None, "--exclude"),
) -> None:
    """
    Sync local folder TO S3 using s5cmd with optional dry-run and filters.
    """
    s5_sync(
        target_bucket=bucket,
        source=local_path / folder,
        context=show_code,
        dry_run=dry_run,
        include=include,
        exclude=exclude,
    )
