from pathlib import Path

import typer

from apps.onepiece.utils.progress import progress_tracker
from libraries.integrations.aws.s5_sync import s5_sync

app = typer.Typer(help="AWS and S3 integration commands")


@app.command("sync-from")
def sync_from(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: str,
    dry_run: bool = False,
    include: list[str] | None = typer.Option(None, "--include"),
    exclude: list[str] | None = typer.Option(None, "--exclude"),
    profile: str | None = None,
) -> None:
    """Sync local folder FROM S3 using s5cmd with optional dry-run and filters."""
    include = include or []
    exclude = exclude or []

    source = f"s3://{bucket}/{show_code}/{folder}"
    destination = Path(local_path)

    with progress_tracker(
        "S3 Download",
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
            source=source,
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
            f"Synchronized {source} → {destination} (dry-run={dry_run!s})."
        )
