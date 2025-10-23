"""Tests covering cost, risk, and PnL calculations for Perona."""

from __future__ import annotations

import pytest

from apps.perona.engine import DEFAULT_CURRENCY, PeronaEngine


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
