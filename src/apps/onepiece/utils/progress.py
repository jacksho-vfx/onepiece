"""Shared progress reporting utilities for CLI commands."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

__all__ = ["progress_tracker", "ProgressHandle"]


@dataclass
class ProgressHandle:
    """Helper that exposes a consistent progress reporting API."""

    _progress: Progress
    _task_id: TaskID
    _console: Console
    _title: str
    _finished: bool = False
    _failed: bool = False

    def advance(self, *, description: Optional[str] = None, step: float = 1.0) -> None:
        """Advance the progress bar and optionally update its description."""

        if description:
            self._progress.update(self._task_id, description=description)
        self._progress.advance(self._task_id, step)

    def update_total(self, total: float) -> None:
        """Update the expected total work units for the task."""

        self._progress.update(self._task_id, total=total)

    def succeed(self, message: str) -> None:
        """Mark the progress as completed and display a success message."""

        if not self._finished:
            task = self._progress.tasks[self._task_id]
            self._progress.update(
                self._task_id, completed=task.total if task.total else task.completed
            )
        self._finished = True
        self._console.print(f"[bold green]✔ {message}[/bold green]")

    def fail(self, message: str) -> None:
        """Mark the progress as failed and display an error message."""

        self._failed = True
        self._console.print(f"[bold red]✖ {message}[/bold red]")


@contextmanager
def progress_tracker(
    title: str,
    *,
    total: float,
    task_description: str,
    console: Optional[Console] = None,
) -> Iterator[ProgressHandle]:
    """Context manager that yields a :class:`ProgressHandle` with shared styling."""

    progress_console = console or Console()
    progress_console.rule(f"[bold cyan]{title}")

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=progress_console,
        transient=False,
    ) as progress:
        task_id = progress.add_task(task_description, total=total)
        handle = ProgressHandle(progress, task_id, progress_console, title)
        try:
            yield handle
        except Exception:  # pragma: no cover - re-raised for CLI exception handlers
            if not handle._failed:
                handle.fail(f"{title} failed.")
            raise
        finally:
            if not handle._finished and not handle._failed:
                handle.succeed(f"{title} completed.")
            progress.stop()
