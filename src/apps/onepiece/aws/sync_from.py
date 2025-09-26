
from upath import UPath
import typer

from src.libraries.aws.s5_sync import s5_sync

app = typer.Typer(help="Sync from an S3 bucket")


@app.command("sync-from")
def sync_from(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: UPath,
    dry_run: bool = False,
    include: list[str] | None = typer.Option(None, "--include"),
    exclude: list[str] | None = typer.Option(None, "--exclude"),
) -> None:
    """
    Sync local folder FROM S3 using s5cmd with optional dry-run and filters.
    """
    s5_sync(
        target_bucket=str(local_path / folder),
        source=UPath(bucket),
        context=show_code,
        dry_run=dry_run,
        include=include,
        exclude=exclude,
    )
