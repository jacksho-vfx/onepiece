from upath import UPath
import typer

from src.libraries.aws.s3_sync import sync_to_bucket

app = typer.Typer(help="Sync to an S3 bucket")


@app.command("sync-to")
def sync_to(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: UPath,
    dry_run: bool = False,
    include: list[str] | None = typer.Option(None, "--include"),
    exclude: list[str] | None = typer.Option(None, "--exclude"),
) -> None:
    """
    Sync a local folder TO S3 using the AWS CLI with optional dry-run and filters.
    """
    include_patterns = list(include or [])
    exclude_patterns = list(exclude or [])

    sync_to_bucket(
        bucket=bucket,
        show_code=show_code,
        folder=folder,
        local_path=local_path / folder,
        include=include_patterns,
        exclude=exclude_patterns,
        dry_run=dry_run,
    )
