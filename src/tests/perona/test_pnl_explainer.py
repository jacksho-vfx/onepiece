"""Tests for the Perona P&L explainer helpers."""

from libraries.analytics.perona import CostDriverDelta, summarise_cost_deltas, total_cost_delta


def test_cost_driver_delta_description() -> None:
    baseline_cost = 1000.0
    delta = CostDriverDelta(
        name="Resolution",
        metric_change_pct=10.0,
        cost_delta=150.0,
        metric_label="resolution",
    )
    assert delta.cost_change_pct(baseline_cost) == 15.0
    assert delta.describe(baseline_cost) == "resolution ↑10% → cost ↑15%"


def test_negative_delta_uses_down_arrow() -> None:
    baseline_cost = 2000.0
    delta = CostDriverDelta(
        name="Spot pricing",
        metric_change_pct=-12.5,
        cost_delta=-160.0,
        metric_label="spot pricing",
    )
    assert delta.cost_change_pct(baseline_cost) == -8.0
    assert delta.describe(baseline_cost) == "spot pricing ↓12.5% → cost ↓8%"


def test_summarise_cost_deltas_and_total() -> None:
    baseline_cost = 500.0
    deltas = (
        CostDriverDelta(
            name="Iterations",
            metric_change_pct=5.0,
            cost_delta=25.0,
            metric_label="iterations",
        ),
        CostDriverDelta(
            name="Pricing",
            metric_change_pct=-3.0,
            cost_delta=-15.0,
            metric_label="pricing",
        ),
    )
    summary = summarise_cost_deltas(baseline_cost, deltas)
    assert summary == ("iterations ↑5% → cost ↑5%", "pricing ↓3% → cost ↓3%")
    assert total_cost_delta(deltas) == 10.0
