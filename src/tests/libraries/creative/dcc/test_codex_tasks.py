from __future__ import annotations

from libraries.creative.dcc.codex import CodexTask, list_codex_tasks


def test_codex_tasks_are_unique_and_complete() -> None:
    tasks = list_codex_tasks()
    assert len(tasks) == 10

    slugs = {task.slug for task in tasks}
    assert len(slugs) == len(tasks)

    for task in tasks:
        assert isinstance(task, CodexTask)
        assert task.dcc
        assert task.title
        assert task.approach
        assert task.deliverables
