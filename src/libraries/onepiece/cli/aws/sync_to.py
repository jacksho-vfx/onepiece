from pathlib import Path
from typing import TypeVar, cast

import typer

from apps.onepiece.utils.progress import progress_tracker
from libraries.integrations.aws.s5_sync import s5_sync

app = typer.Typer(help="AWS and S3 integration commands")
T = TypeVar("T")


def _resolve_override(name: str, default: T) -> T:
    from apps.onepiece.aws import sync_to as sync_to_module

    override = getattr(sync_to_module, name, None)
    if override is not None and override is not default:
        return cast(T, override)
    return default


@app.command("sync-to")
def sync_to(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: str,
    dry_run: bool = False,
    include: list[str] | None = typer.Option(None, "--include"),
    exclude: list[str] | None = typer.Option(None, "--exclude"),
    profile: str | None = None,
    concurrency: int | None = typer.Option(
        None,
        "--concurrency",
        min=1,
        help="Override the s5cmd --concurrency value for uploads.",
    ),
    part_size: str | None = typer.Option(
        None,
        "--part-size",
        help="Override the s5cmd --part-size value (for example '64MB').",
    ),
) -> None:
    """Sync local folder TO S3 using s5cmd with optional dry-run and filters."""
    include = include or []
    exclude = exclude or []

    source = str(Path(local_path))  # normalize path safely
    destination = f"s3://{bucket}/{show_code}/{folder}"

    with _resolve_override("progress_tracker", progress_tracker)(
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

        # ✅ send plain strings, not Paths
        _resolve_override("s5_sync", s5_sync)(
            source=source,
            destination=destination,
            dry_run=dry_run,
            include=include,
            exclude=exclude,
            progress_callback=_on_progress,
            profile=profile,
            concurrency=concurrency,
            part_size=part_size,
        )

        if events == 0:
            progress.advance(description="Sync completed")

        progress.update_total(max(events, 1))
        progress.succeed(
            f"Synchronized {source} → {destination} (dry-run={dry_run!s})."
        )
