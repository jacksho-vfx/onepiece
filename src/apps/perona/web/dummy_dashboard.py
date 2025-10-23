"""FastAPI application exposing a static Perona demo surface.

The real Perona dashboard streams live metrics sourced from production
pipelines.  For demos, documentation, and development environments it is
useful to stand up a deterministic set of responses without requiring any
external services.  This module reuses the core analytical helpers from
``apps.perona.web.dashboard`` but serves them from an in-memory
``PeronaEngine`` instance whose data never changes.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse

from apps.perona.engine import PeronaEngine
from apps.perona.models import (
    CostEstimate,
    CostEstimateRequest,
    OptimizationBacktestRequest,
    OptimizationBacktestResponse,
    PnLBreakdown,
    RenderMetric,
    RiskIndicator,
    SettingsSummary,
    Shot,
    Sequence as PeronaSequence,
)
from apps.perona.version import PERONA_VERSION
from apps.perona.web import dashboard as live_dashboard


app = FastAPI(
    title="Perona (Demo)",
    description=(
        "Static demonstration endpoints that mirror the live Perona "
        "dashboard.  All data is deterministic and generated from the "
        "bundled defaults so the web experience can be showcased without "
        "connecting to production systems."
    ),
    version=PERONA_VERSION,
)


_ENGINE = PeronaEngine()
_SETTINGS_SUMMARY = SettingsSummary.from_engine(
    _ENGINE,
    settings_path=None,
    warnings=(
        "Serving dummy data sourced from the packaged defaults. "
        "Values do not reflect a live render farm."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    """Simple readiness check for the demo server."""

    return {"status": "ok", "mode": "demo"}


@app.get("/settings", response_model=SettingsSummary)
def settings_summary() -> SettingsSummary:
    """Return the static configuration snapshot that seeds the demo."""

    return _SETTINGS_SUMMARY


@app.post("/settings/reload", response_model=SettingsSummary)
def settings_reload() -> SettingsSummary:
    """Mirror the real reload endpoint but keep the static payload."""

    return _SETTINGS_SUMMARY


@app.get("/render-feed", response_model=list[RenderMetric])
def render_feed(
    limit: int = Query(30, ge=1, le=250),
    sequence: str | None = Query(None),
    shot_id: str | None = Query(None),
) -> Any:
    """Return render telemetry samples from the demo engine."""

    return live_dashboard.render_feed(
        limit=limit, sequence=sequence, shot_id=shot_id, engine=_ENGINE
    )


@app.get("/render-feed/live")
async def render_feed_stream(
    limit: int = Query(30, ge=1, le=250),
    sequence: str | None = Query(None),
    shot_id: str | None = Query(None),
) -> Any:
    """Stream newline-delimited telemetry for widgets that expect live data."""

    return await live_dashboard.render_feed_stream(
        limit=limit, sequence=sequence, shot_id=shot_id, engine=_ENGINE
    )


@app.get("/metrics")
def metrics_summary() -> Any:
    """Expose aggregated statistics calculated from the demo telemetry."""

    return live_dashboard.metrics_summary(engine=_ENGINE)


@app.post("/cost/estimate", response_model=CostEstimate)
def cost_estimate(payload: CostEstimateRequest) -> CostEstimate:
    """Estimate render costs using the deterministic demo engine."""

    return live_dashboard.cost_estimate(payload=payload, engine=_ENGINE)


@app.get("/risk-heatmap", response_model=list[RiskIndicator])
def risk_heatmap() -> Any:
    """Return the static render risk ordering from the demo dataset."""

    return live_dashboard.risk_heatmap(engine=_ENGINE)


@app.get("/pnl", response_model=PnLBreakdown)
def pnl() -> PnLBreakdown:
    """Return the deterministic P&L breakdown bundled with the demo."""

    return live_dashboard.pnl(engine=_ENGINE)


@app.post("/optimization/backtest", response_model=OptimizationBacktestResponse)
def optimization_backtest(
    payload: OptimizationBacktestRequest,
) -> OptimizationBacktestResponse:
    """Execute what-if optimisation scenarios against the demo data."""

    return live_dashboard.optimization_backtest(payload=payload, engine=_ENGINE)


@app.get("/shots/lifecycle", response_model=list[Shot])
def shots_lifecycle(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
) -> Any:
    """Return the canned lifecycle timelines for monitored demo shots."""

    return live_dashboard.shots_lifecycle(
        sequence=sequence,
        artist=artist,
        start_date=start_date,
        end_date=end_date,
        engine=_ENGINE,
    )


@app.get("/shots/sequences", response_model=list[PeronaSequence])
def shot_sequences(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
) -> Any:
    """Return demo shots grouped by sequence for gallery style views."""

    return live_dashboard.shots_sequences(
        sequence=sequence,
        artist=artist,
        start_date=start_date,
        end_date=end_date,
        engine=_ENGINE,
    )


@app.get("/shots")
def shots_summary(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
) -> Any:
    """Summarise shot progress using the deterministic lifecycle data."""

    return live_dashboard.shots_summary(
        sequence=sequence,
        artist=artist,
        start_date=start_date,
        end_date=end_date,
        engine=_ENGINE,
    )


@app.get("/risk")
def risk_summary() -> Any:
    """Return aggregate risk metadata derived from the demo indicators."""

    return live_dashboard.risk_summary(engine=_ENGINE)


@app.get("/costs")
def costs_summary() -> Any:
    """Return combined cost and P&L data for the demo dataset."""

    return live_dashboard.costs_summary(engine=_ENGINE)


@app.get("/reports/daily")
def daily_report(format: str = Query("csv")) -> Any:
    """Generate the daily summary report in CSV or PDF form."""

    return live_dashboard.daily_report(format=format, engine=_ENGINE)


@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket) -> None:
    """Continuously push demo telemetry samples over a WebSocket feed."""

    await websocket.accept()
    try:
        while True:
            for sample in _ENGINE.stream_render_metrics(limit=30):
                payload = RenderMetric.from_entity(sample).model_dump(
                    mode="json", by_alias=True
                )
                await websocket.send_json(payload)
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


@app.post("/metrics/ingest")
async def ingest_metrics() -> dict[str, str]:
    """Dummy endpoint mirroring the live ingest surface."""

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Metric ingestion is disabled for the demo server.",
    )


@app.get("/render-feed/live/sample")
async def render_feed_sample(limit: int = Query(5, ge=1, le=50)) -> StreamingResponse:
    """Return a short NDJSON sample without waiting for the stream."""

    metrics = live_dashboard.render_feed(
        limit=limit, sequence=None, shot_id=None, engine=_ENGINE
    )

    async def _generator() -> Any:
        for metric in metrics:
            yield json.dumps(metric.model_dump(mode="json", by_alias=True)) + "\n"

    return StreamingResponse(_generator(), media_type="application/x-ndjson")


__all__ = ["app"]
