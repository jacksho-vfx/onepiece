from upath import UPath
import typer

from apps.onepiece.utils.progress import progress_tracker
from libraries.aws.s5_sync import s5_sync

app = typer.Typer(help="AWS and S3 integration commands")


@app.command("sync-to")
def sync_to(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: UPath,
    dry_run: bool = False,
    include: list[str] | None = typer.Option(None, "--include"),
    exclude: list[str] | None = typer.Option(None, "--exclude"),
    profile: str | None = None,
) -> None:
    """
    Sync local folder TO S3 using s5cmd with optional dry-run and filters.
    """
    include = include or []
    exclude = exclude or []

    destination = f"s3://{bucket}/{show_code}/{folder}"

    with progress_tracker(
        "S3 Upload",
        total=1,
        task_description="Running s5cmd sync",
    ) as progress:
        events = 0

        def _on_progress(line: str) -> None:
            nonlocal events
            events += 1
            progress.update_total(events + 1)
            description = line or "Syncing files"
            progress.advance(description=description)

        s5_sync(
            source=local_path / folder,
            destination=destination,
            dry_run=dry_run,
            include=include,
            exclude=exclude,
            progress_callback=_on_progress,
            profile=profile,
        )

        if events == 0:
            progress.advance(description="Sync completed")

        progress.update_total(max(events, 1))
        progress.succeed(
            f"Synchronized {local_path / folder} → {destination} (dry-run={dry_run!s})."
        )
