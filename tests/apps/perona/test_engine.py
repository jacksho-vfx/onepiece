"""Unit tests for the Perona analytics engine."""

from __future__ import annotations

import itertools
from pathlib import Path
from textwrap import dedent

import pytest

from apps.perona.engine import (
    CostModelInput,
    OptimizationScenario,
    PeronaEngine,
)


@pytest.fixture()
def engine() -> PeronaEngine:
    return PeronaEngine()


def test_estimate_cost_breakdown(engine: PeronaEngine) -> None:
    inputs = CostModelInput(
        frame_count=120,
        average_frame_time_ms=180.0,
        gpu_hourly_rate=9.5,
        gpu_count=32,
        render_farm_hourly_rate=6.2,
        storage_gb=8.5,
        storage_rate_per_gb=0.4,
        data_egress_gb=2.3,
        egress_rate_per_gb=0.2,
        misc_costs=95.0,
    )
    breakdown = engine.estimate_cost(inputs)
    assert breakdown.frame_count == 120
    assert breakdown.concurrency == 32
    assert breakdown.total_cost == pytest.approx(98.92, rel=1e-4)
    assert breakdown.cost_per_frame == pytest.approx(0.8243, rel=1e-4)


def test_risk_heatmap_is_sorted(engine: PeronaEngine) -> None:
    scores = [item.risk_score for item in engine.risk_heatmap()]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] >= 90


def test_pnl_explainer_consistency(engine: PeronaEngine) -> None:
    breakdown = engine.pnl_explainer()
    contribution_total = sum(item.delta_cost for item in breakdown.contributions)
    assert contribution_total == pytest.approx(breakdown.delta_cost)
    assert breakdown.current_cost == pytest.approx(
        breakdown.baseline_cost + breakdown.delta_cost
    )


def test_optimization_backtest_adjusts_cost(engine: PeronaEngine) -> None:
    baseline, scenarios = engine.run_optimization_backtest(
        [
            OptimizationScenario(
                name="Ampere Fleet",
                gpu_count=72,
                gpu_hourly_rate=7.8,
                frame_time_scale=0.9,
            )
        ]
    )
    assert len(scenarios) == 1
    scenario = scenarios[0]
    assert scenario.total_cost < baseline.total_cost
    assert "gpu count" in scenario.notes
    assert scenario.savings_vs_baseline > 0


def test_shot_lifecycle_exposes_current_stage(engine: PeronaEngine) -> None:
    lifecycles = engine.shot_lifecycle()
    assert lifecycles
    for lifecycle in lifecycles:
        open_stage_count = len(
            [stage for stage in lifecycle.stages if stage.completed_at is None]
        )
        assert lifecycle.current_stage in {stage.name for stage in lifecycle.stages}
        if open_stage_count:
            assert lifecycle.current_stage in {
                stage.name for stage in lifecycle.stages if stage.completed_at is None
            }


def test_stream_render_metrics_limit(engine: PeronaEngine) -> None:
    limited = list(itertools.islice(engine.stream_render_metrics(limit=5), 5))
    assert len(limited) == 5
    timestamps = [metric.timestamp for metric in limited]
    assert timestamps == sorted(timestamps)


def test_from_settings_loads_default_configuration() -> None:
    engine = PeronaEngine.from_settings()
    baseline = engine.baseline_cost_input
    assert baseline.gpu_count == 64
    assert baseline.gpu_hourly_rate == pytest.approx(8.75)
    assert engine.target_error_rate == pytest.approx(0.012)
    assert engine.pnl_explainer().baseline_cost == pytest.approx(18240.0)


def test_from_settings_applies_custom_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "settings.toml"
    config_path.write_text(
        dedent(
            """
            target_error_rate = 0.02
            pnl_baseline_cost = 9876.5

            [baseline_cost_input]
            frame_count = 1440
            average_frame_time_ms = 200.0
            gpu_hourly_rate = 12.5
            gpu_count = 48
            render_farm_hourly_rate = 4.5
            storage_gb = 6.0
            storage_rate_per_gb = 0.45
            data_egress_gb = 2.0
            egress_rate_per_gb = 0.55
            misc_costs = 150.0
            """
        ).strip()
    )
    engine = PeronaEngine.from_settings(path=config_path)
    baseline = engine.baseline_cost_input
    assert baseline.frame_count == 1440
    assert baseline.gpu_hourly_rate == pytest.approx(12.5)
    assert engine.target_error_rate == pytest.approx(0.02)
    assert engine.pnl_explainer().baseline_cost == pytest.approx(9876.5)


def test_constructor_accepts_injected_baseline() -> None:
    custom_input = CostModelInput(
        frame_count=720,
        average_frame_time_ms=110.0,
        gpu_hourly_rate=6.5,
        gpu_count=24,
        render_farm_hourly_rate=3.5,
        storage_gb=4.0,
        storage_rate_per_gb=0.3,
        data_egress_gb=1.2,
        egress_rate_per_gb=0.2,
        misc_costs=50.0,
    )
    engine = PeronaEngine(
        baseline_input=custom_input,
        target_error_rate=0.05,
        pnl_baseline_cost=4321.0,
    )
    assert engine.baseline_cost_input == custom_input
    assert engine.target_error_rate == pytest.approx(0.05)
    assert engine.pnl_explainer().baseline_cost == pytest.approx(4321.0)
