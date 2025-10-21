"""FastAPI surface exposing Perona dashboard analytics."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse

from apps.perona.version import PERONA_VERSION

from apps.perona.engine import PeronaEngine
from apps.perona.models import (
    CostEstimate,
    CostEstimateRequest,
    OptimizationBacktestRequest,
    OptimizationBacktestResponse,
    OptimizationResult,
    PnLBreakdown,
    RenderMetric,
    RiskIndicator,
    Shot,
)

app = FastAPI(
    title="Perona",
    description=(
        "Real-time VFX performance & cost dashboard inspired by quant trading systems. "
        "The API surfaces telemetry, risk scoring, cost attribution and optimisation "
        "backtests that power the interactive UI."
    ),
    version=PERONA_VERSION,
)

_engine = PeronaEngine.from_settings()


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health endpoint for uptime checks."""

    return {"status": "ok"}


@app.get("/render-feed", response_model=list[RenderMetric])
def render_feed(limit: int = Query(30, ge=1, le=250)) -> list[RenderMetric]:
    """Return recent render telemetry samples for dashboard widgets."""

    metrics = [
        RenderMetric.from_entity(metric)
        for metric in _engine.stream_render_metrics(limit)
    ]
    return metrics


@app.get("/render-feed/live")
async def render_feed_stream(limit: int = Query(30, ge=1, le=250)) -> StreamingResponse:
    """Stream telemetry samples using newline delimited JSON."""

    async def _generator() -> Any:
        for metric in _engine.stream_render_metrics(limit):
            model = RenderMetric.from_entity(metric)
            payload = model.model_dump(mode="json", by_alias=True)
            yield json.dumps(payload) + "\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(_generator(), media_type="application/x-ndjson")


@app.post("/cost/estimate", response_model=CostEstimate)
def cost_estimate(payload: CostEstimateRequest) -> CostEstimate:
    """Estimate the cost per frame for the supplied inputs."""

    breakdown = _engine.estimate_cost(payload.to_entity())
    return CostEstimate.from_breakdown(breakdown)


@app.get("/risk-heatmap", response_model=list[RiskIndicator])
def risk_heatmap() -> list[RiskIndicator]:
    """Return the current render risk heatmap."""

    return [RiskIndicator.from_entity(item) for item in _engine.risk_heatmap()]


@app.get("/pnl", response_model=PnLBreakdown)
def pnl() -> PnLBreakdown:
    """Return the P&L attribution summary for the latest render window."""

    breakdown = _engine.pnl_explainer()
    return PnLBreakdown.from_entity(breakdown)


@app.post("/optimization/backtest", response_model=OptimizationBacktestResponse)
def optimization_backtest(
    payload: OptimizationBacktestRequest,
) -> OptimizationBacktestResponse:
    """Run what-if optimisation scenarios and return their cost impact."""

    scenarios = [item.to_entity() for item in payload.scenarios]
    baseline, results = _engine.run_optimization_backtest(scenarios)
    return OptimizationBacktestResponse(
        baseline=CostEstimate.from_breakdown(baseline),
        scenarios=tuple(OptimizationResult.from_entity(item) for item in results),
    )


@app.get("/shots/lifecycle", response_model=list[Shot])
def shots_lifecycle() -> list[Shot]:
    """Return lifecycle timelines for key monitored shots."""

    return [Shot.from_entity(item) for item in _engine.shot_lifecycle()]


__all__ = ["app"]
