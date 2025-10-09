"""Tests covering the AWS sync CLI wrappers."""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from typer.testing import CliRunner

from apps.onepiece.app import app


def _invoke(command: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(app, command)
    return result.exit_code, result.output


def _capture_s5_sync(monkeypatch: pytest.MonkeyPatch, module: str) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _fake_s5_sync(**kwargs: Any) -> None:
        captured.update(kwargs)

    class _ProgressStub:
        def update_total(self, total: float) -> None:
            return None

        def advance(self, *, description: str | None = None, step: float = 1.0) -> None:
            return None

        def succeed(self, message: str) -> None:
            return None

    @contextmanager
    def _fake_progress_tracker(*args: Any, **kwargs: Any) -> Any:
        yield _ProgressStub()

    module_obj = importlib.import_module(module)

    monkeypatch.setattr(module_obj, "s5_sync", _fake_s5_sync)
    monkeypatch.setattr(module_obj, "progress_tracker", _fake_progress_tracker)

    return captured


def test_sync_from_cli_forwards_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _capture_s5_sync(monkeypatch, "apps.onepiece.aws.sync_from")

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


def test_sync_to_cli_forwards_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _capture_s5_sync(monkeypatch, "apps.onepiece.aws.sync_to")

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
