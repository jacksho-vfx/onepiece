from __future__ import annotations

import pytest

from libraries.automation.render.optimization import (
    AdapterDefaults,
    CostBreakdown,
    CostModelInput,
    FarmMetrics,
    OptimizationProjection,
    OptimizationScenario,
    SubmissionOptimizationDecision,
    compute_submission_adjustments,
    estimate_cost,
    simulate_optimizations,
)


def test_estimate_cost_returns_breakdown() -> None:
    inputs = CostModelInput(
        frame_count=240,
        average_frame_time_ms=120_000.0,
        gpu_hourly_rate=8.0,
        gpu_count=4,
        render_farm_hourly_rate=3.5,
        storage_gb=12.0,
        storage_rate_per_gb=0.25,
        data_egress_gb=2.5,
        egress_rate_per_gb=0.1,
        misc_costs=45.0,
    )

    breakdown = estimate_cost(inputs)

    assert isinstance(breakdown, CostBreakdown)
    assert breakdown.frame_count == 240
    assert breakdown.concurrency == 4
    assert breakdown.gpu_hours == pytest.approx(8.0)
    assert breakdown.render_hours == pytest.approx(2.0)
    assert breakdown.gpu_cost == pytest.approx(64.0)
    assert breakdown.render_farm_cost == pytest.approx(7.0)
    assert breakdown.storage_cost == pytest.approx(3.0)
    assert breakdown.egress_cost == pytest.approx(0.25)
    assert breakdown.misc_cost == pytest.approx(45.0)
    assert breakdown.total_cost == pytest.approx(119.25)
    assert breakdown.cost_per_frame == pytest.approx(0.4969, rel=1e-4)


def test_simulate_optimizations_computes_savings() -> None:
    baseline = CostModelInput(
        frame_count=1200,
        average_frame_time_ms=150_000.0,
        gpu_hourly_rate=9.5,
        gpu_count=12,
        render_farm_hourly_rate=4.0,
        storage_gb=18.0,
        storage_rate_per_gb=0.42,
        data_egress_gb=6.0,
        egress_rate_per_gb=0.18,
        misc_costs=110.0,
    )

    scenarios = [
        OptimizationScenario(
            name="Next-gen GPU",
            gpu_hourly_rate=7.8,
            gpu_count=10,
            frame_time_scale=0.82,
            sampling_scale=0.7,
            resolution_scale=0.9,
        ),
        OptimizationScenario(
            name="Aggressive sampling",
            frame_time_scale=0.75,
            sampling_scale=0.55,
        ),
    ]

    baseline_breakdown, results = simulate_optimizations(baseline, scenarios)

    assert baseline_breakdown.total_cost == pytest.approx(610.31)
    assert len(results) == 2
    assert all(isinstance(item, OptimizationProjection) for item in results)

    first = results[0]
    assert first.name == "Next-gen GPU"
    assert first.breakdown.total_cost == pytest.approx(352.54)
    assert first.savings == pytest.approx(257.77)
    assert first.savings_percent == pytest.approx(42.24)

    second = results[1]
    assert second.breakdown.gpu_cost < baseline_breakdown.gpu_cost
    assert second.savings > 0


def test_simulate_optimizations_rejects_invalid_gpu_count() -> None:
    baseline = CostModelInput(
        frame_count=10,
        average_frame_time_ms=100.0,
        gpu_hourly_rate=1.0,
        gpu_count=1,
    )

    with pytest.raises(ValueError):
        simulate_optimizations(
            baseline,
            [OptimizationScenario(name="invalid", gpu_count=0)],
        )


def test_compute_submission_adjustments_short_frame_range() -> None:
    defaults = AdapterDefaults(
        default_priority=50,
        priority_min=0,
        priority_max=100,
        default_chunk_size=6,
        chunk_size_min=1,
        chunk_size_max=12,
        chunk_size_enabled=True,
    )

    decision = compute_submission_adjustments(12, defaults)

    assert isinstance(decision, SubmissionOptimizationDecision)
    assert decision.priority == 55
    assert decision.chunk_size == 2
    assert "short frame range" in " ".join(decision.reasons)
    assert decision.applied is True


def test_compute_submission_adjustments_long_frame_range_and_metrics() -> None:
    defaults = AdapterDefaults(
        default_priority=55,
        priority_min=10,
        priority_max=95,
        default_chunk_size=4,
        chunk_size_min=1,
        chunk_size_max=10,
        chunk_size_enabled=True,
    )
    metrics = FarmMetrics(queue_depth=120, average_frame_time_ms=1000.0)

    decision = compute_submission_adjustments(400, defaults, metrics=metrics)

    assert decision.priority >= 60
    assert decision.chunk_size >= 8
    joined = " ".join(decision.reasons)
    assert "very high queue depth" in joined
    assert "long frame range" in joined
    assert decision.applied is True
