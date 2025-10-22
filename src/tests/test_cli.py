"""Regression tests for the Perona Typer CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from apps.perona.app import DEFAULT_HOST, DEFAULT_PORT, app
from apps.perona.engine import (
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_PNL_BASELINE_COST,
    DEFAULT_SETTINGS_PATH,
    DEFAULT_TARGET_ERROR_RATE,
)
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
    assert "Currency" in result.output
    assert "GBP" in result.output
    assert "Warnings:" not in result.output


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
currency = "USD"
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
    assert "Currency" in result.output
    assert "USD" in result.output


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
currency = "USD"
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
    assert payload["baseline_cost_input"]["currency"] == "USD"
    assert payload["warnings"] == []


def test_settings_command_supports_diff_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)

    settings_path = tmp_path / "diff.toml"
    settings_path.write_text(
        """
target_error_rate = 0.02
pnl_baseline_cost = 19000.0

[baseline_cost_input]
gpu_hourly_rate = 9.75
frame_count = 3000
""".strip()
    )

    result = runner.invoke(
        app, ["settings", "--settings-path", str(settings_path), "--diff"]
    )

    assert result.exit_code == 0
    assert "Differences from defaults" in result.output
    assert "Baseline cost inputs" in result.output
    assert "(Δ +1.0, default 8.75)" in result.output
    assert "(Δ +312, default 2,688)" in result.output
    assert "(Δ +0.008, default 0.012)" in result.output
    assert "(Δ +760.0, default 18,240.0)" in result.output


def test_settings_command_supports_diff_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)

    settings_path = tmp_path / "diff-json.toml"
    settings_path.write_text(
        """
target_error_rate = 0.02
pnl_baseline_cost = 19000.0

[baseline_cost_input]
gpu_hourly_rate = 9.75
frame_count = 3000
""".strip()
    )

    result = runner.invoke(
        app,
        [
            "settings",
            "--settings-path",
            str(settings_path),
            "--format",
            "json",
            "--diff",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["target_error_rate"] == 0.02
    differences = payload.get("differences")
    assert differences is not None
    assert payload["warnings"] == []

    baseline_diffs = differences["baseline_cost_input"]
    assert baseline_diffs["gpu_hourly_rate"]["current"] == 9.75
    assert baseline_diffs["gpu_hourly_rate"]["default"] == pytest.approx(
        DEFAULT_BASELINE_COST_INPUT.gpu_hourly_rate
    )
    assert baseline_diffs["gpu_hourly_rate"]["delta"] == pytest.approx(1.0)

    frame_diff = baseline_diffs["frame_count"]
    assert frame_diff["current"] == 3000
    assert frame_diff["default"] == DEFAULT_BASELINE_COST_INPUT.frame_count
    assert frame_diff["delta"] == 312

    target_diff = differences["target_error_rate"]
    assert target_diff["current"] == 0.02
    assert target_diff["default"] == pytest.approx(DEFAULT_TARGET_ERROR_RATE)
    assert target_diff["delta"] == pytest.approx(0.008)

    pnl_diff = differences["pnl_baseline_cost"]
    assert pnl_diff["current"] == 19000.0
    assert pnl_diff["default"] == DEFAULT_PNL_BASELINE_COST
    assert pnl_diff["delta"] == pytest.approx(760)


def test_settings_command_reports_env_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing_path = tmp_path / "missing.toml"
    monkeypatch.setenv("PERONA_SETTINGS_PATH", str(missing_path))

    result = runner.invoke(app, ["settings"])

    assert result.exit_code == 1
    assert "Warnings:" in result.output
    assert str(missing_path) in result.output
    assert "falling back to defaults" in result.output


def test_settings_command_reports_env_fallback_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing_path = tmp_path / "missing.toml"
    monkeypatch.setenv("PERONA_SETTINGS_PATH", str(missing_path))

    result = runner.invoke(app, ["settings", "--format", "json"])

    assert result.exit_code == 1
    output = result.output
    json_text, warnings_text = output.split("\n\nWarnings:\n", maxsplit=1)
    payload = json.loads(json_text)
    assert payload["settings_path"] == str(DEFAULT_SETTINGS_PATH.expanduser())
    assert payload["warnings"]
    warning_lines = [line.strip("- ") for line in warnings_text.strip().splitlines()]
    assert any(str(missing_path) in line for line in warning_lines)


def test_settings_command_rejects_missing_path(tmp_path: Path) -> None:
    missing_path = tmp_path / "absent.toml"

    result = runner.invoke(app, ["settings", "--settings-path", str(missing_path)])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_settings_command_rejects_unreadable_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings_path = tmp_path / "blocked.toml"
    settings_path.write_text("target_error_rate = 0.2")
    monkeypatch.setattr("apps.perona.app.os.access", lambda path, mode: False)

    result = runner.invoke(app, ["settings", "--settings-path", str(settings_path)])

    assert result.exit_code != 0
    assert "readable" in result.output


def test_dashboard_command_sets_settings_path_env(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    env_key = "PERONA_SETTINGS_PATH"
    os.environ.pop(env_key, None)

    uvicorn_run = mocker.Mock()
    uvicorn_module = mocker.Mock(run=uvicorn_run)
    mocker.patch("apps.perona.app.import_module", return_value=uvicorn_module)

    settings_path = tmp_path / "custom.toml"
    settings_path.write_text("target_error_rate = 0.1")

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


def test_dashboard_command_rejects_invalid_settings_path(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch("apps.perona.app.import_module")
    missing_path = tmp_path / "missing.toml"

    result = runner.invoke(
        app,
        ["web", "dashboard", "--settings-path", str(missing_path)],
    )

    assert result.exit_code != 0
    terms = ["does", "not", "exist"]
    for term in terms:
        assert term in result.output


def test_settings_export_writes_default_settings(tmp_path: Path) -> None:
    destination = tmp_path / "perona" / "settings.toml"
    destination.parent.mkdir()

    result = runner.invoke(app, ["settings-export", str(destination)])

    assert result.exit_code == 0
    assert destination.read_text() == DEFAULT_SETTINGS_PATH.read_text()
    assert str(destination) in result.output


def test_settings_export_refuses_to_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "perona.toml"
    destination.write_text("original")

    result = runner.invoke(app, ["settings-export", str(destination)])

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert destination.read_text() == "original"


def test_cost_estimate_command_outputs_table() -> None:
    result = runner.invoke(
        app,
        [
            "cost",
            "estimate",
            "--frame-count",
            "300",
            "--average-frame-time-ms",
            "90",
            "--gpu-hourly-rate",
            "4.5",
            "--storage-gb",
            "12",
            "--storage-rate-per-gb",
            "0.4",
        ],
    )

    assert result.exit_code == 0
    assert "Cost estimate" in result.output
    assert "Storage cost" in result.output
    assert "Total cost" in result.output


def test_cost_estimate_command_supports_json_output() -> None:
    result = runner.invoke(
        app,
        [
            "cost",
            "estimate",
            "--frame-count",
            "120",
            "--average-frame-time-ms",
            "80",
            "--gpu-hourly-rate",
            "3.5",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["frame_count"] == 120
    assert payload["concurrency"] == 1
    assert payload["gpu_cost"] == 0.01
    assert payload["currency"] == "GBP"


def test_cost_estimate_command_accepts_currency_override() -> None:
    result = runner.invoke(
        app,
        [
            "cost",
            "estimate",
            "--frame-count",
            "60",
            "--average-frame-time-ms",
            "160",
            "--gpu-hourly-rate",
            "5.0",
            "--currency",
            "usd",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["currency"] == "USD"


def test_cost_estimate_command_reports_validation_errors() -> None:
    result = runner.invoke(
        app,
        [
            "cost",
            "estimate",
            "--frame-count",
            "0",
            "--average-frame-time-ms",
            "100",
            "--gpu-hourly-rate",
            "5",
        ],
    )

    assert result.exit_code != 0
    assert "frame_count" in result.output
    assert "greater than 0" in result.output


def test_cost_estimate_command_rejects_unknown_currency() -> None:
    result = runner.invoke(
        app,
        [
            "cost",
            "estimate",
            "--frame-count",
            "100",
            "--average-frame-time-ms",
            "120",
            "--gpu-hourly-rate",
            "4.5",
            "--currency",
            "aud",
        ],
    )

    assert result.exit_code != 0
    assert "currency must be one of" in result.output


def test_settings_export_can_force_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "perona.toml"
    destination.write_text("original")

    result = runner.invoke(
        app,
        ["settings-export", str(destination), "--force"],
    )

    assert result.exit_code == 0
    assert destination.read_text() == DEFAULT_SETTINGS_PATH.read_text()
