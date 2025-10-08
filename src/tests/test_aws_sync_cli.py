"""Tests covering the AWS sync CLI wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from typer.testing import CliRunner

from apps.onepiece.app import app


def _invoke(command: list[str]) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(app, command)
    return result.exit_code, result.output


def test_sync_from_cli_forwards_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def _fake_sync_from(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("apps.onepiece.aws.sync_from_command", _fake_sync_from)

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


def test_sync_to_cli_forwards_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def _fake_sync_to(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("apps.onepiece.aws.sync_to_command", _fake_sync_to)

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
