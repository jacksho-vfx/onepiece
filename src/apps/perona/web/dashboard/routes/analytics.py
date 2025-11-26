"""Analytics and cost intelligence routes."""

from __future__ import annotations

from statistics import fmean
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.perona.web.dashboard import dependencies
from libraries.analytics.perona.engine.engine import PeronaEngine
from libraries.analytics.perona.models import (
    CostEstimate,
    CostEstimateRequest,
    CostInsightResponse,
    OptimizationBacktestRequest,
    OptimizationBacktestResponse,
    OptimizationResult,
    PnLBreakdown,
    RiskIndicator,
)

router = APIRouter(tags=["analytics"])


def compute_risk_summary(engine: PeronaEngine) -> dict[str, Any]:
    """Return risk score distribution for the monitored shot portfolio."""

    indicators = list(engine.risk_heatmap())
    if not indicators:
        return {
            "count": 0,
            "average_risk": 0.0,
            "max_risk": None,
            "min_risk": None,
            "top_risks": [],
            "critical": [],
        }

    average_risk = round(fmean(item.risk_score for item in indicators), 2)
    top_three = [
        RiskIndicator.from_entity(item).model_dump(mode="json")
        for item in indicators[:3]
    ]
    critical = [
        RiskIndicator.from_entity(item).model_dump(mode="json")
        for item in indicators
        if item.risk_score >= 75
    ]

    return {
        "count": len(indicators),
        "average_risk": average_risk,
        "max_risk": indicators[0].risk_score,
        "min_risk": indicators[-1].risk_score,
        "top_risks": top_three,
        "critical": critical,
    }


def compute_costs_summary(engine: PeronaEngine) -> dict[str, Any]:
    """Return key spend metrics combining baseline and current projections."""

    baseline_input = engine.baseline_cost_input
    baseline_breakdown = engine.estimate_cost(baseline_input)
    pnl_breakdown = engine.pnl_explainer()

    baseline_payload = CostEstimate.from_breakdown(baseline_breakdown).model_dump(
        mode="json"
    )
    pnl_payload = PnLBreakdown.from_entity(pnl_breakdown).model_dump(mode="json")

    frame_count = max(baseline_breakdown.frame_count, 1)
    baseline_cost_per_frame = round(baseline_breakdown.cost_per_frame, 4)
    current_cost_per_frame = round(pnl_breakdown.current_cost / frame_count, 4)
    delta_cost_per_frame = round(current_cost_per_frame - baseline_cost_per_frame, 4)

    samples = tuple(engine.stream_render_metrics())
    timeline: list[dict[str, Any]] = []
    sequence_totals: dict[str, dict[str, float]] = {}

    baseline_frame_time = max(baseline_input.average_frame_time_ms, 1e-6)
    for sample in samples:
        sequence_data = sequence_totals.setdefault(
            sample.sequence,
            {"frame_time_total": 0.0, "count": 0},
        )
        sequence_data["frame_time_total"] += sample.frame_time_ms
        sequence_data["count"] += 1

        current_series_cost = round(
            baseline_cost_per_frame * (sample.frame_time_ms / baseline_frame_time), 4
        )
        timeline.append(
            {
                "timestamp": sample.timestamp.isoformat(),
                "sequence": sample.sequence,
                "baseline_cost_per_frame": baseline_cost_per_frame,
                "current_cost_per_frame": current_series_cost,
            }
        )

    timeline.sort(key=lambda item: item["timestamp"])

    sequence_series = []
    for sequence, totals in sequence_totals.items():
        if totals["count"] <= 0:
            continue
        average_frame_time = totals["frame_time_total"] / totals["count"]
        sequence_series.append(
            {
                "sequence": sequence,
                "average_frame_time_ms": round(average_frame_time, 2),
                "baseline_cost_per_frame": baseline_cost_per_frame,
                "current_cost_per_frame": round(
                    baseline_cost_per_frame
                    * (average_frame_time / baseline_frame_time),
                    4,
                ),
            }
        )

    return {
        "baseline": baseline_payload,
        "pnl": pnl_payload,
        "currency": baseline_breakdown.currency,
        "cost_per_frame": {
            "baseline": baseline_cost_per_frame,
            "current": current_cost_per_frame,
            "delta": delta_cost_per_frame,
        },
        "series": {
            "timeline": timeline,
            "by_sequence": sorted(sequence_series, key=lambda item: item["sequence"]),
        },
    }


@router.get("/risk")
def risk_summary(
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> dict[str, Any]:
    """Return risk score distribution for the monitored shot portfolio."""

    return compute_risk_summary(engine)


@router.get("/risk-heatmap", response_model=list[RiskIndicator])
def risk_heatmap(
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> list[RiskIndicator]:
    """Return the current render risk heatmap."""

    return [RiskIndicator.from_entity(item) for item in engine.risk_heatmap()]


@router.get("/costs")
def costs_summary(
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> dict[str, Any]:
    """Return key spend metrics combining baseline and current projections."""

    return compute_costs_summary(engine)


@router.post("/cost/estimate", response_model=CostEstimate)
def cost_estimate(
    payload: CostEstimateRequest,
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> CostEstimate:
    """Estimate the cost per frame for the supplied inputs."""

    breakdown = engine.estimate_cost(payload.to_entity())
    return CostEstimate.from_breakdown(breakdown)


@router.get("/api/cost/insights", response_model=CostInsightResponse)
def cost_insights(
    top_n: int = Query(3, ge=1, le=10),
    refresh_telemetry: bool = Query(
        False, alias="refresh_telemetry", description="Reload persisted telemetry"
    ),
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> CostInsightResponse:
    """Return descriptive statistics and optimisation suggestions."""

    statistics, recommendations = dependencies.get_cost_insights(
        engine, top_n=top_n, refresh_telemetry=refresh_telemetry
    )

    if not statistics:
        raise HTTPException(
            status_code=404,
            detail="No telemetry statistics available.",
        )

    cache_entry = dependencies.get_engine_cache_entry()
    return CostInsightResponse.from_results(
        statistics,
        recommendations,
        settings_path=cache_entry.settings_path,
    )


@router.get("/pnl", response_model=PnLBreakdown)
def pnl(engine: PeronaEngine = Depends(dependencies.get_engine)) -> PnLBreakdown:
    """Return the P&L attribution summary for the latest render window."""

    breakdown = engine.pnl_explainer()
    return PnLBreakdown.from_entity(breakdown)


@router.post("/optimization/backtest", response_model=OptimizationBacktestResponse)
def optimization_backtest(
    payload: OptimizationBacktestRequest,
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> OptimizationBacktestResponse:
    """Run what-if optimisation scenarios and return their cost impact."""

    scenarios = [item.to_entity() for item in payload.scenarios]
    baseline, results = engine.run_optimization_backtest(scenarios)
    return OptimizationBacktestResponse(
        baseline=CostEstimate.from_breakdown(baseline),
        scenarios=tuple(OptimizationResult.from_entity(item) for item in results),
    )


__all__ = ["router", "compute_costs_summary", "compute_risk_summary"]
