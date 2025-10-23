"""Tests covering cost, risk, and PnL calculations for Perona."""

from __future__ import annotations

from datetime import timedelta
import time

import pytest

from apps.perona.engine import (
    DEFAULT_CURRENCY,
    PeronaEngine,
    RenderMetric,
    ShotTelemetry,
)


@pytest.fixture()
def engine() -> PeronaEngine:
    return PeronaEngine()


def test_cost_breakdown_for_baseline_inputs(engine: PeronaEngine) -> None:
    """Baseline inputs should generate the expected cost metrics."""

    breakdown = engine.estimate_cost(engine.baseline_cost_input)

    assert breakdown.frame_count == 2688
    assert breakdown.concurrency == 64
    assert breakdown.currency == DEFAULT_CURRENCY
    assert breakdown.gpu_hours == pytest.approx(0.1060, rel=1e-3)
    assert breakdown.render_hours == pytest.approx(0.0017, rel=1e-3)
    assert breakdown.gpu_cost == pytest.approx(0.93, rel=1e-3)
    assert breakdown.storage_cost == pytest.approx(4.71, rel=1e-3)
    assert breakdown.total_cost == pytest.approx(226.37, rel=1e-4)
    assert breakdown.cost_per_frame == pytest.approx(0.0842, rel=1e-4)


def test_risk_heatmap_scores_and_drivers(engine: PeronaEngine) -> None:
    """Risk scores should be stable and surface key driver narratives."""

    heatmap = engine.risk_heatmap()

    assert len(heatmap) == 4
    top_risk = heatmap[0]
    assert top_risk.shot_id == "SQ09_SH180"
    assert top_risk.risk_score == pytest.approx(87.07, abs=0.01)
    assert "Error rate high (+166.7% vs target)" in top_risk.drivers

    lowest_risk = heatmap[-1]
    assert lowest_risk.shot_id == "SQ05_SH045"
    assert lowest_risk.risk_score == pytest.approx(12.07, abs=0.01)
    assert lowest_risk.drivers == ("Render time volatility",)


def test_risk_heatmap_uses_cached_frame_times(engine: PeronaEngine) -> None:
    """Frame time grouping should not require re-scanning the render log."""

    original_log = engine._render_log
    try:

        class FailOnIter:
            def __iter__(self) -> AssertionError:
                raise AssertionError("render log should not be iterated")

        engine._render_log = FailOnIter()
        heatmap = engine.risk_heatmap()
    finally:
        engine._render_log = original_log

    assert len(heatmap) == 4


def test_risk_heatmap_large_log_benefits_from_caching(engine: PeronaEngine) -> None:
    """Pre-grouped frame times drastically reduce lookups on large logs."""

    base_telemetry = engine._telemetry
    base_log = engine._render_log

    multiplier = 200
    expanded_telemetry: list[ShotTelemetry] = []
    expanded_log: list[RenderMetric] = []

    for index in range(multiplier):
        delta = timedelta(minutes=index)
        for telemetry in base_telemetry:
            sequence = f"{telemetry.sequence}_{index}"
            shot_id = f"{telemetry.shot_id}_{index}"
            expanded_telemetry.append(
                ShotTelemetry(
                    sequence=sequence,
                    shot_id=shot_id,
                    average_frame_time_ms=telemetry.average_frame_time_ms,
                    fps=telemetry.fps,
                    error_rate=telemetry.error_rate,
                    cache_stability=telemetry.cache_stability,
                    frames_rendered=telemetry.frames_rendered,
                    deadline=telemetry.deadline + delta,
                )
            )
            for sample in base_log:
                expanded_log.append(
                    RenderMetric(
                        sequence=sequence,
                        shot_id=shot_id,
                        timestamp=sample.timestamp + delta,
                        fps=sample.fps,
                        frame_time_ms=sample.frame_time_ms,
                        error_count=sample.error_count,
                        gpu_utilisation=sample.gpu_utilisation,
                        cache_health=sample.cache_health,
                    )
                )

    engine._telemetry = tuple(expanded_telemetry)
    engine._render_log = tuple(expanded_log)
    engine._frame_times_by_shot = engine._group_frame_times(engine._render_log)

    start = time.perf_counter()
    naive_grouping = [
        [
            sample.frame_time_ms
            for sample in engine._render_log
            if sample.sequence == telemetry.sequence
            and sample.shot_id == telemetry.shot_id
        ]
        for telemetry in engine._telemetry
    ]
    naive_duration = time.perf_counter() - start

    start = time.perf_counter()
    cached_grouping = [
        engine._frame_times_by_shot[(telemetry.sequence, telemetry.shot_id)]
        for telemetry in engine._telemetry
    ]
    cached_duration = time.perf_counter() - start

    heatmap = engine.risk_heatmap()

    assert heatmap
    assert naive_grouping
    assert cached_grouping
    assert cached_duration * 3 < naive_duration


def test_pnl_breakdown_contributions(engine: PeronaEngine) -> None:
    """PnL breakdown should reconcile totals and detailed contributions."""

    breakdown = engine.pnl_explainer()

    assert breakdown.baseline_cost == pytest.approx(18240.0)
    assert breakdown.delta_cost == pytest.approx(3648.0)
    assert breakdown.current_cost == pytest.approx(21888.0)

    contributions = breakdown.contributions
    assert [item.factor for item in contributions] == [
        "Resolution scale",
        "Sampling iterations",
        "Shot revisions",
        "GPU spot pricing",
        "Queue efficiency",
    ]
    assert contributions[0].delta_cost == pytest.approx(2736.0)
    assert contributions[1].percentage_points == pytest.approx(12.0)
    assert contributions[3].narrative == "spot pricing ↓7% → cost ↓8%"
