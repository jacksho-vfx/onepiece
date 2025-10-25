"""Tests for the progress tracking utilities used across the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from typing import Any

from rich.console import Console

from apps.onepiece.utils.progress import ProgressHandle


@dataclass
class _StubTask:
    """Minimal task record mirroring the attributes accessed by the handle."""

    total: float | None
    completed: float


class _StubProgress:
    """Progress implementation whose task IDs do not align with list indices."""

    def __init__(self, tasks: dict[int, _StubTask]) -> None:
        self._tasks = tasks
        # ``ProgressHandle`` previously indexed ``tasks`` by ID which fails when the
        # IDs do not map directly to the list position.  The list intentionally
        # omits the task referenced by ``_task_id`` to exercise the resilient path.
        self.tasks: list[_StubTask] = []
        self.updates: list[tuple[int, dict[str, Any]]] = []

    def get_task(self, task_id: int) -> _StubTask:
        return self._tasks[task_id]

    def update(self, task_id: int, **kwargs: Any) -> None:
        self.updates.append((task_id, dict(kwargs)))
        task = self._tasks[task_id]
        if "total" in kwargs and kwargs["total"] is not None:
            task.total = float(kwargs["total"])
        if "completed" in kwargs and kwargs["completed"] is not None:
            task.completed = float(kwargs["completed"])

    def advance(
        self, task_id: int, step: float = 1.0, description: str | None = None
    ) -> None:  # pragma: no cover - interface compatibility.
        return None

    def stop(self) -> None:  # pragma: no cover - interface compatibility.
        return None


def test_progress_handle_succeed_uses_task_lookup() -> None:
    """Ensure ``ProgressHandle.succeed`` resolves tasks by ID."""

    task_id = 7
    task = _StubTask(total=3.0, completed=1.0)
    progress = _StubProgress({task_id: task})
    console = Console(file=StringIO(), force_terminal=False, color_system=None)

    handle = ProgressHandle(progress, task_id, console, "Ingest")
    handle.succeed("Finished ingest")

    assert handle._finished is True
    assert progress.updates == [(task_id, {"completed": 3.0})]
    assert "✔ Finished ingest" in console.file.getvalue()  # type: ignore[attr-defined]
