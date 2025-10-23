from __future__ import annotations

import json
import socket
from urllib.error import URLError

import pytest
import pytest_mock

from apps.perona.app import (
    DEFAULT_SETTINGS_RELOAD_TIMEOUT,
    SETTINGS_RELOAD_TIMEOUT_ENV,
    _post_settings_reload,
)
from apps.perona.models import BaselineCostInput, SettingsSummary


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


def test_post_settings_reload_uses_default_timeout(
    monkeypatch: pytest.MonkeyPatch, mocker: pytest_mock.MockerFixture
) -> None:
    monkeypatch.delenv(SETTINGS_RELOAD_TIMEOUT_ENV, raising=False)
    summary = _make_settings_summary()
    payload = json.dumps(summary.model_dump(mode="json")).encode("utf-8")

    response = mocker.MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = payload
    response.status = 200

    urlopen_mock = mocker.patch("apps.perona.app.urlopen", return_value=response)

    result = _post_settings_reload("http://perona.test")

    assert result.model_dump() == summary.model_dump()
    assert urlopen_mock.call_args.kwargs["timeout"] == DEFAULT_SETTINGS_RELOAD_TIMEOUT


def test_post_settings_reload_reports_timeout(
    monkeypatch: pytest.MonkeyPatch, mocker: pytest_mock.MockerFixture
) -> None:
    monkeypatch.delenv(SETTINGS_RELOAD_TIMEOUT_ENV, raising=False)
    urlopen_mock = mocker.patch("apps.perona.app.urlopen")
    urlopen_mock.side_effect = URLError(socket.timeout("timed out"))

    with pytest.raises(RuntimeError) as excinfo:
        _post_settings_reload("http://perona.test")

    assert "timed out" in str(excinfo.value).lower()
    assert str(DEFAULT_SETTINGS_RELOAD_TIMEOUT) in str(excinfo.value)


def test_post_settings_reload_timeout_respects_env(
    monkeypatch: pytest.MonkeyPatch, mocker: pytest_mock.MockerFixture
) -> None:
    monkeypatch.setenv(SETTINGS_RELOAD_TIMEOUT_ENV, "12.5")
    urlopen_mock = mocker.patch("apps.perona.app.urlopen")
    urlopen_mock.side_effect = URLError(socket.timeout("timed out"))

    with pytest.raises(RuntimeError) as excinfo:
        _post_settings_reload("http://perona.test")

    assert "12.5" in str(excinfo.value)
    assert urlopen_mock.call_args.kwargs["timeout"] == pytest.approx(12.5)
