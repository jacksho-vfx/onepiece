"""Regression tests for the Perona Typer CLI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from apps.perona.app import DEFAULT_HOST, DEFAULT_PORT, app
from apps.perona.version import PERONA_VERSION


runner = CliRunner()


def test_version_command_outputs_perona_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert PERONA_VERSION in result.output


def test_settings_command_uses_active_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The settings command prints the resolved Perona settings file."""

    settings_path = tmp_path / "perona.toml"
    settings_path.write_text("target_error_rate = 0.42\n")

    monkeypatch.setenv("PERONA_SETTINGS_PATH", str(settings_path))

    result = runner.invoke(app, ["settings"])
    path_result = runner.invoke(app, ["settings", "--show-path"])

    assert result.exit_code == 0
    assert "target_error_rate = 0.42" in result.output
    assert path_result.exit_code == 0
    assert path_result.output.strip() == str(settings_path)


def test_dashboard_command_sets_settings_path_env(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    env_key = "PERONA_SETTINGS_PATH"
    os.environ.pop(env_key, None)

    uvicorn_run = mocker.Mock()
    uvicorn_module = mocker.Mock(run=uvicorn_run)
    mocker.patch("apps.perona.app.import_module", return_value=uvicorn_module)

    settings_path = tmp_path / "custom.toml"

    try:
        result = runner.invoke(
            app,
            ["web", "dashboard", "--settings-path", str(settings_path)],
        )

        assert result.exit_code == 0
        assert os.environ[env_key] == str(settings_path)
        uvicorn_run.assert_called_once_with(
            "apps.perona.web.dashboard:app",
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            reload=False,
            log_level="info",
        )
    finally:
        os.environ.pop(env_key, None)
