from __future__ import annotations

from pathlib import Path

import pytest
import pytest_mock
from typer.testing import CliRunner

from apps.perona.app import app as perona_app
from apps.perona.models import BaselineCostInput, SettingsSummary


runner = CliRunner()


def _make_settings_summary() -> SettingsSummary:
    return SettingsSummary(
        baseline_cost_input=BaselineCostInput(
            frame_count=1200,
            average_frame_time_ms=140.0,
            gpu_hourly_rate=9.5,
            gpu_count=32,
            render_hours=0.0,
            render_farm_hourly_rate=5.25,
            storage_gb=12.4,
            storage_rate_per_gb=0.38,
            data_egress_gb=3.8,
            egress_rate_per_gb=0.19,
            misc_costs=220.0,
            currency="GBP",
        ),
        target_error_rate=0.012,
        pnl_baseline_cost=180000.0,
        warnings=(),
    )


def test_settings_reload_adds_default_scheme_for_explicit_host(
    mocker: pytest_mock.MockerFixture,
) -> None:
    summary = _make_settings_summary()
    post_mock = mocker.patch(
        "apps.perona.app._post_settings_reload", return_value=summary
    )

    result = runner.invoke(
        perona_app,
        ["settings", "reload", "--url", "perona.internal.example:9000"],
    )

    assert result.exit_code == 0
    post_mock.assert_called_once_with("http://perona.internal.example:9000")


def test_settings_reload_adds_default_scheme_for_env(
    monkeypatch: pytest.MonkeyPatch, mocker: pytest_mock.MockerFixture
) -> None:
    monkeypatch.setenv("PERONA_DASHBOARD_URL", "perona.cluster.example")
    summary = _make_settings_summary()
    post_mock = mocker.patch(
        "apps.perona.app._post_settings_reload", return_value=summary
    )

    result = runner.invoke(perona_app, ["settings", "reload"])

    assert result.exit_code == 0
    post_mock.assert_called_once_with("http://perona.cluster.example")


def test_settings_rejects_directory_settings_path(
    tmp_path: Path, mocker: pytest_mock.MockerFixture
) -> None:
    directory = tmp_path / "settings"
    directory.mkdir()

    from_settings = mocker.patch("apps.perona.app.PeronaEngine.from_settings")

    result = runner.invoke(
        perona_app, ["settings", "--settings-path", str(directory)]
    )

    assert result.exit_code == 2
    assert "Settings path" in result.output
    from_settings.assert_not_called()
