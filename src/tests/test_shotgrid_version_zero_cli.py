"""Tests for the ShotGrid version-zero CLI command."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.onepiece.utils.errors import OnePieceValidationError

version_zero = importlib.import_module("apps.onepiece.shotgrid.version_zero")

runner = CliRunner()


class _MissingProjectShotGridClient:
    def get_project_id_by_name(self, project_name: str) -> None:  # noqa: D401 - stub
        return None


class _ShotGridClientFactory:
    @staticmethod
    def from_env() -> _MissingProjectShotGridClient:
        return _MissingProjectShotGridClient()


def test_version_zero_errors_when_project_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    csv_path = tmp_path / "shots.csv"
    csv_path.write_text("shot\nE01_S01_SH001\n")

    monkeypatch.setattr(version_zero, "ShotGridClient", _ShotGridClientFactory)

    result = runner.invoke(
        version_zero.app,
        [str(csv_path), "--project-name", "MissingProject"],
    )

    assert isinstance(result.exception, OnePieceValidationError)
    message = str(result.exception)
    assert "MissingProject" in message
    assert "Project" in message
