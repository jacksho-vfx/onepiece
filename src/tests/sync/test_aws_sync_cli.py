"""Tests covering the AWS sync CLI wrappers."""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app


def _invoke(command: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(app, command)
    return result.exit_code, result.output


def _capture_s5_sync(monkeypatch: pytest.MonkeyPatch, module: str) -> dict[str, Any]:
    """Patch both s5_sync() and progress_tracker() inside the given module."""
    captured: dict[str, Any] = {}

    def _fake_s5_sync(**kwargs: Any) -> None:
        captured.update(kwargs)

    class _ProgressStub:
        def update_total(self, total: float) -> None: ...
        def advance(
            self, *, description: str | None = None, step: float = 1.0
        ) -> None: ...
        def succeed(self, message: str) -> None: ...

    @contextmanager
    def _fake_progress_tracker(*args: Any, **kwargs: Any) -> Any:
        yield _ProgressStub()

    # Always reload to ensure patched version is used by Typer
    module_obj = importlib.reload(importlib.import_module(module))

    monkeypatch.setattr(module_obj, "s5_sync", _fake_s5_sync)
    monkeypatch.setattr(module_obj, "progress_tracker", _fake_progress_tracker)

    return captured


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_sync_from_cli_forwards_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import importlib
    from contextlib import contextmanager
    from apps.onepiece.app import app

    sync_from_mod = importlib.import_module("apps.onepiece.aws.sync_from")

    captured: dict[str, Any] = {}

    def _fake_s5_sync(**kwargs: Any) -> None:
        captured.update(kwargs)

    class _ProgressStub:
        def update_total(self, total: float) -> None: ...
        def advance(
            self, *, description: str | None = None, step: float = 1.0
        ) -> None: ...
        def succeed(self, message: str) -> None: ...

    @contextmanager
    def _fake_progress_tracker(
        *args: Any, **kwargs: Any
    ) -> Generator[_ProgressStub, Any, None]:
        yield _ProgressStub()

    monkeypatch.setattr(sync_from_mod, "s5_sync", _fake_s5_sync)
    monkeypatch.setattr(sync_from_mod, "progress_tracker", _fake_progress_tracker)

    import apps.onepiece.aws as aws_pkg

    monkeypatch.setattr(aws_pkg, "sync_from", sync_from_mod.sync_from)

    # ---- critical: replace Typer’s command callback ----
    for group_info in app.registered_groups:
        subapp = getattr(group_info, "typer_instance", None)
        if subapp and subapp.info.name == "aws":
            for cmd_info in subapp.registered_commands:
                if cmd_info.name == "sync-from":
                    cmd_info.callback = sync_from_mod.sync_from
                    break

    exit_code, _ = _invoke(
        [
            "aws",
            "sync-from",
            "bucket",
            "SHOW",
            "plates",
            str(tmp_path),
            "--profile",
            "studio-prod",
        ]
    )

    assert exit_code == 0
    assert captured["profile"] == "studio-prod"
    assert captured["source"] == "s3://bucket/SHOW/plates"
    assert Path(captured["destination"]) == tmp_path


def test_sync_to_cli_forwards_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import importlib
    from contextlib import contextmanager
    from apps.onepiece.app import app

    sync_to_mod = importlib.import_module("apps.onepiece.aws.sync_to")

    captured: dict[str, Any] = {}

    def _fake_s5_sync(**kwargs: Any) -> None:
        captured.update(kwargs)

    class _ProgressStub:
        def update_total(self, total: float) -> None: ...
        def advance(
            self, *, description: str | None = None, step: float = 1.0
        ) -> None: ...
        def succeed(self, message: str) -> None: ...

    @contextmanager
    def _fake_progress_tracker(
        *args: Any, **kwargs: Any
    ) -> Generator[_ProgressStub, Any, None]:
        yield _ProgressStub()

    monkeypatch.setattr(sync_to_mod, "s5_sync", _fake_s5_sync)
    monkeypatch.setattr(sync_to_mod, "progress_tracker", _fake_progress_tracker)

    import apps.onepiece.aws as aws_pkg

    monkeypatch.setattr(aws_pkg, "sync_to", sync_to_mod.sync_to)

    # ---- critical: replace Typer’s command callback ----
    for group_info in app.registered_groups:
        subapp = getattr(group_info, "typer_instance", None)
        if subapp and subapp.info.name == "aws":
            for cmd_info in subapp.registered_commands:
                if cmd_info.name == "sync-to":
                    cmd_info.callback = sync_to_mod.sync_to
                    break

    exit_code, _ = _invoke(
        [
            "aws",
            "sync-to",
            "bucket",
            "SHOW",
            "plates",
            str(tmp_path),
            "--profile",
            "studio-prod",
        ]
    )

    assert exit_code == 0
    assert captured["profile"] == "studio-prod"
    assert captured["destination"] == "s3://bucket/SHOW/plates"
    assert Path(captured["source"]) == tmp_path
