"""FastAPI surface exposing Perona dashboard analytics."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from apps.perona.version import PERONA_VERSION

from . import dependencies
from .routes import (
    analytics,
    metrics,
    reports as report_routes,
    shots,
    system,
    wrangler,
)
from .templates import dashboard_index_html

app = FastAPI(
    title="Perona",
    description=(
        "Real-time VFX performance & cost dashboard inspired by quant trading systems. "
        "The API surfaces telemetry, risk scoring, cost attribution and optimisation "
        "backtests that power the interactive UI."
    ),
    version=PERONA_VERSION,
)

app.include_router(system.router)
app.include_router(wrangler.router)
app.include_router(metrics.router)
app.include_router(analytics.router)
app.include_router(shots.router)
app.include_router(report_routes.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard_ui() -> HTMLResponse:
    """Serve the modern Perona dashboard HTML shell."""

    return HTMLResponse(content=dashboard_index_html())


# Public re-exports for compatibility
RenderMetricBatch = dependencies.RenderMetricBatch
RenderMetricStore = dependencies.RenderMetricStore
persist_metrics = dependencies.persist_metrics
metrics_store_path = dependencies.metrics_store_path

# Route handlers surfaced for script integrations and tests
dashboard_summary = report_routes.dashboard_summary
daily_report = report_routes.daily_report

metrics_summary = metrics.metrics_summary
render_feed = metrics.render_feed
render_feed_stream = metrics.render_feed_stream
ingest_render_metrics = metrics.ingest_render_metrics
metrics_websocket = metrics.metrics_websocket

risk_summary = analytics.risk_summary
costs_summary = analytics.costs_summary
cost_estimate = analytics.cost_estimate
cost_insights = analytics.cost_insights
pnl = analytics.pnl
optimization_backtest = analytics.optimization_backtest

shots_summary = shots.shots_summary
shots_lifecycle = shots.shots_lifecycle
shot_sequences = shots.shot_sequences

# Internal hooks preserved for backwards compatibility
_metrics_store = getattr(dependencies, "_metrics_store")
_CostInsightsMemo = getattr(dependencies, "_CostInsightsMemo")
_resolved_settings_path = getattr(dependencies, "_resolved_settings_path")
_settings_signature = getattr(dependencies, "_settings_signature")
_get_engine_cache_entry = dependencies.get_engine_cache_entry
_load_engine = getattr(dependencies, "_load_engine")
_settings_summary_from_cache = getattr(dependencies, "_settings_summary_from_cache")
_engine_cache = getattr(dependencies, "_engine_cache")


def get_engine(refresh: bool = Query(False, alias="refresh_engine")) -> Any:
    """FastAPI dependency yielding the shared Perona engine instance."""

    return _load_engine(refresh)


def invalidate_engine_cache() -> None:
    """Clear the cached engine so it will be rebuilt on next use."""

    dependencies.invalidate_engine_cache()


reload_settings = dependencies.reload_settings


def __getattr__(name: str) -> object:
    if hasattr(dependencies, name):
        return getattr(dependencies, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __setattr__(name: str, value: object) -> None:
    globals()[name] = value
    if hasattr(dependencies, name):
        dependencies.__dict__[name] = value


__all__ = ["app", "get_engine", "invalidate_engine_cache", "reload_settings"]
