"""Regression tests for the Perona Typer CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from apps.perona.app import DEFAULT_HOST, DEFAULT_PORT, app
from apps.perona.engine import DEFAULT_SETTINGS_PATH
from apps.perona.version import PERONA_VERSION


runner = CliRunner()


def test_version_command_outputs_perona_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert PERONA_VERSION in result.output


def test_settings_command_displays_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default settings should be materialised via PeronaEngine."""

    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)

    result = runner.invoke(app, ["settings"])

    assert result.exit_code == 0
    assert str(DEFAULT_SETTINGS_PATH) in result.output
    assert "GPU Hourly Rate" in result.output
    assert "8.75" in result.output
    assert "Target error rate" in result.output
    assert "0.012" in result.output
    assert "P&L baseline cost" in result.output
    assert "18,240" in result.output


def test_settings_command_honours_custom_settings_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)

    settings_path = tmp_path / "perona.toml"
    settings_path.write_text(
        """
target_error_rate = 0.42
pnl_baseline_cost = 9999.5

[baseline_cost_input]
frame_count = 12
average_frame_time_ms = 55.5
gpu_hourly_rate = 15.75
misc_costs = 12.0
""".strip()
    )

    result = runner.invoke(app, ["settings", "--settings-path", str(settings_path)])

    assert result.exit_code == 0
    assert str(settings_path) in result.output
    assert "Frame Count" in result.output
    assert "12" in result.output
    assert "55.5" in result.output
    assert "15.75" in result.output
    assert "0.42" in result.output
    assert "9,999.5" in result.output


def test_settings_command_supports_json_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)

    settings_path = tmp_path / "engine.toml"
    settings_path.write_text(
        """
target_error_rate = 0.25
pnl_baseline_cost = 5432.1

[baseline_cost_input]
frame_count = 48
average_frame_time_ms = 21.5
gpu_hourly_rate = 4.2
""".strip()
    )

    result = runner.invoke(
        app,
        ["settings", "--settings-path", str(settings_path), "--format", "JSON"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["settings_path"] == str(settings_path)
    assert payload["target_error_rate"] == 0.25
    assert payload["pnl_baseline_cost"] == 5432.1
    assert payload["baseline_cost_input"]["frame_count"] == 48
    assert payload["baseline_cost_input"]["average_frame_time_ms"] == 21.5
    assert payload["baseline_cost_input"]["gpu_hourly_rate"] == 4.2


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
