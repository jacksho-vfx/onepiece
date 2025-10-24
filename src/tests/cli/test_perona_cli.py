from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_mock
from typer.testing import CliRunner

from apps.perona.engine import CostBreakdown, CostModelInput, SettingsLoadResult
from libraries.analytics.perona.ml_foundations import FeatureStatistics
from apps.perona.app import app as perona_app
from apps.perona.models import BaselineCostInput, SettingsSummary


runner = CliRunner()


class _StubCostEngine:
    def __init__(self, baseline: CostModelInput) -> None:
        self._baseline = baseline
        self.last_inputs: CostModelInput | None = None

    @property
    def baseline_cost_input(self) -> CostModelInput:
        return self._baseline

    def estimate_cost(self, inputs: CostModelInput) -> CostBreakdown:
        self.last_inputs = inputs
        gpu_cost = inputs.gpu_hourly_rate * inputs.gpu_count
        render_farm_cost = inputs.render_farm_hourly_rate
        storage_cost = inputs.storage_gb * inputs.storage_rate_per_gb
        egress_cost = inputs.data_egress_gb * inputs.egress_rate_per_gb
        misc_cost = inputs.misc_costs
        total_cost = (
            gpu_cost + render_farm_cost + storage_cost + egress_cost + misc_cost
        )
        cost_per_frame = total_cost / inputs.frame_count if inputs.frame_count else 0.0
        return CostBreakdown(
            frame_count=inputs.frame_count,
            gpu_hours=inputs.render_hours,
            render_hours=inputs.render_hours,
            concurrency=inputs.gpu_count,
            gpu_cost=gpu_cost,
            render_farm_cost=render_farm_cost,
            storage_cost=storage_cost,
            egress_cost=egress_cost,
            misc_cost=misc_cost,
            total_cost=total_cost,
            cost_per_frame=cost_per_frame,
            currency=inputs.currency,
        )


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

    result = runner.invoke(perona_app, ["settings", "--settings-path", str(directory)])

    assert result.exit_code == 2
    assert "Settings path" in result.output
    from_settings.assert_not_called()


def test_cost_estimate_applies_baseline_defaults_in_table_output(
    mocker: pytest_mock.MockerFixture,
) -> None:
    baseline = CostModelInput(
        frame_count=987,
        average_frame_time_ms=118.0,
        gpu_hourly_rate=7.25,
        gpu_count=6,
        render_hours=12.0,
        render_farm_hourly_rate=4.25,
        storage_gb=9.5,
        storage_rate_per_gb=0.55,
        data_egress_gb=1.8,
        egress_rate_per_gb=0.22,
        misc_costs=45.0,
        currency="USD",
    )
    engine = _StubCostEngine(baseline)
    mocker.patch(
        "apps.perona.app.PeronaEngine.from_settings",
        return_value=SettingsLoadResult(engine=engine, settings_path=None, warnings=()),
    )

    result = runner.invoke(perona_app, ["cost", "estimate"])

    assert result.exit_code == 0
    assert engine.last_inputs is not None
    assert engine.last_inputs.frame_count == baseline.frame_count
    assert engine.last_inputs.gpu_hourly_rate == baseline.gpu_hourly_rate
    assert "Currency" in result.output
    assert "USD" in result.output
    assert "$" in result.output


def test_cost_estimate_settings_path_overrides_defaults(
    tmp_path: Path, mocker: pytest_mock.MockerFixture
) -> None:
    default_baseline = CostModelInput(
        frame_count=1024,
        average_frame_time_ms=140.0,
        gpu_hourly_rate=8.0,
        gpu_count=8,
        render_hours=10.0,
        render_farm_hourly_rate=5.0,
        storage_gb=12.0,
        storage_rate_per_gb=0.4,
        data_egress_gb=2.0,
        egress_rate_per_gb=0.3,
        misc_costs=100.0,
        currency="GBP",
    )
    override_baseline = CostModelInput(
        frame_count=2048,
        average_frame_time_ms=132.0,
        gpu_hourly_rate=9.5,
        gpu_count=12,
        render_hours=14.0,
        render_farm_hourly_rate=6.5,
        storage_gb=18.0,
        storage_rate_per_gb=0.6,
        data_egress_gb=3.5,
        egress_rate_per_gb=0.4,
        misc_costs=150.0,
        currency="USD",
    )
    default_engine = _StubCostEngine(default_baseline)
    override_engine = _StubCostEngine(override_baseline)
    settings_file = tmp_path / "perona.toml"
    settings_file.write_text("# overrides")

    def _from_settings(*, path: Path | None) -> SettingsLoadResult:
        if path is None:
            return SettingsLoadResult(
                engine=default_engine, settings_path=None, warnings=()
            )
        assert path == settings_file
        return SettingsLoadResult(
            engine=override_engine, settings_path=path, warnings=()
        )

    from_settings = mocker.patch(
        "apps.perona.app.PeronaEngine.from_settings", side_effect=_from_settings
    )

    default_result = runner.invoke(perona_app, ["cost", "estimate", "--format", "json"])
    override_result = runner.invoke(
        perona_app,
        [
            "cost",
            "estimate",
            "--format",
            "json",
            "--settings-path",
            str(settings_file),
        ],
    )

    assert default_result.exit_code == 0
    assert override_result.exit_code == 0

    default_payload = json.loads(default_result.output)
    override_payload = json.loads(override_result.output)

    assert default_payload["currency"] == default_baseline.currency
    assert override_payload["currency"] == override_baseline.currency
    assert default_payload["frame_count"] == default_baseline.frame_count
    assert override_payload["frame_count"] == override_baseline.frame_count
    assert default_payload != override_payload

    assert from_settings.call_args_list[0].kwargs == {"path": None}
    assert from_settings.call_args_list[1].kwargs == {"path": settings_file}


def test_cost_insights_renders_table_output(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    statistics = (
        FeatureStatistics(
            name="frame_time_ms",
            mean=124.5,
            stddev=12.3,
            minimum=110.0,
            maximum=140.0,
        ),
        FeatureStatistics(
            name="gpu_utilisation",
            mean=0.78,
            stddev=0.08,
            minimum=0.62,
            maximum=0.89,
        ),
    )
    recommendations = (
        "Trim shading passes to reduce frame_time_ms.",
        "Balance workloads to stabilise gpu_utilisation.",
    )
    engine = mocker.Mock()
    engine.cost_insights.return_value = (statistics, recommendations)
    settings_file = tmp_path / "perona.toml"
    settings_result = SettingsLoadResult(
        engine=engine, settings_path=settings_file, warnings=()
    )
    mocker.patch(
        "apps.perona.app.PeronaEngine.from_settings", return_value=settings_result
    )

    result = runner.invoke(perona_app, ["cost", "insights"])

    assert result.exit_code == 0
    engine.cost_insights.assert_called_once_with()
    output = result.output
    assert f"Settings file: {settings_file}" in output
    assert "Cost telemetry insights" in output
    assert "Frame Time ms" in output
    assert "GPU Utilisation" in output
    assert "Recommendations" in output
    assert "- Trim shading passes" in output


def test_cost_insights_emits_json_payload(
    mocker: pytest_mock.MockerFixture, tmp_path: Path
) -> None:
    statistics = (
        FeatureStatistics(
            name="render_hours",
            mean=1.2,
            stddev=0.3,
            minimum=0.6,
            maximum=1.8,
        ),
    )
    recommendations = ("Optimise render_hours with caching tweaks.",)
    engine = mocker.Mock()
    engine.cost_insights.return_value = (statistics, recommendations)
    settings_file = tmp_path / "overrides.toml"
    settings_result = SettingsLoadResult(
        engine=engine, settings_path=settings_file, warnings=()
    )
    mocker.patch(
        "apps.perona.app.PeronaEngine.from_settings", return_value=settings_result
    )

    result = runner.invoke(perona_app, ["cost", "insights", "--format", "json"])

    assert result.exit_code == 0
    engine.cost_insights.assert_called_once_with()
    payload = json.loads(result.output)
    stats = payload["statistics"]
    assert len(stats) == 1
    stat = stats[0]
    assert stat["name"] == "render_hours"
    assert stat["mean"] == pytest.approx(1.2)
    assert stat["stddev"] == pytest.approx(0.3)
    assert stat["minimum"] == pytest.approx(0.6)
    assert stat["maximum"] == pytest.approx(1.8)
    assert payload["recommendations"] == ["Optimise render_hours with caching tweaks."]
    assert payload["settings_path"] == str(settings_file)


def test_cost_insights_handles_missing_data(
    mocker: pytest_mock.MockerFixture,
) -> None:
    engine = mocker.Mock()
    engine.cost_insights.return_value = ((), ())
    settings_result = SettingsLoadResult(engine=engine, settings_path=None, warnings=())
    mocker.patch(
        "apps.perona.app.PeronaEngine.from_settings", return_value=settings_result
    )

    result = runner.invoke(perona_app, ["cost", "insights"])

    assert result.exit_code == 0
    engine.cost_insights.assert_called_once_with()
    assert "No telemetry statistics available." in result.output
    assert "No recommendations generated." in result.output
