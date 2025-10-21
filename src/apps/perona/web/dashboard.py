"""FastAPI surface exposing Perona dashboard analytics."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, NamedTuple

from fastapi import Depends, FastAPI, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from apps.perona.version import PERONA_VERSION

from apps.perona.engine import (
    CostBreakdown,
    CostModelInput,
    DEFAULT_SETTINGS_PATH,
    OptimizationResult,
    OptimizationScenario,
    PeronaEngine,
    PnLBreakdown,
    PnLContribution,
    RenderMetric,
    RiskIndicator,
    ShotLifecycle,
    ShotLifecycleStage,
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


class _EngineCacheEntry(NamedTuple):
    engine: PeronaEngine
    signature: tuple[str | None, str, float | None]


_engine_lock = Lock()
_engine_cache: _EngineCacheEntry | None = None


def _settings_signature() -> tuple[str | None, str, float | None]:
    """Return the cache signature for the current settings configuration."""

    env_path = os.getenv("PERONA_SETTINGS_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(DEFAULT_SETTINGS_PATH)

    resolved: Path | None = None
    mtime: float | None = None
    for candidate in candidates:
        try:
            stat_result = candidate.stat()
        except FileNotFoundError:
            continue
        else:
            resolved = candidate
            mtime = stat_result.st_mtime
            break

    if resolved is None:
        resolved = candidates[-1]

    return (env_path, str(resolved), mtime)


def _load_engine(force_refresh: bool) -> PeronaEngine:
    """Return a cached engine instance, reloading when configuration changes."""

    global _engine_cache

    signature = _settings_signature()
    with _engine_lock:
        cache_entry = _engine_cache
        if (
            force_refresh
            or cache_entry is None
            or cache_entry.signature != signature
        ):
            engine = PeronaEngine.from_settings()
            cache_entry = _EngineCacheEntry(engine=engine, signature=signature)
            _engine_cache = cache_entry
        return cache_entry.engine


def invalidate_engine_cache() -> None:
    """Clear the cached engine so it will be rebuilt on next use."""

    global _engine_cache
    with _engine_lock:
        _engine_cache = None


def get_engine(
    refresh: bool = Query(False, alias="refresh_engine")
) -> PeronaEngine:
    """FastAPI dependency yielding the shared Perona engine instance."""

    return _load_engine(refresh)


class RenderMetricModel(BaseModel):
    sequence: str
    shot_id: str
    timestamp: datetime
    fps: float
    frame_time_ms: float
    error_count: int
    gpu_utilisation: float = Field(..., alias="gpuUtilisation")
    cache_health: float = Field(..., alias="cacheHealth")

    @classmethod
    def from_entity(cls, metric: RenderMetric) -> "RenderMetricModel":
        data = metric.__dict__.copy()
        data["gpuUtilisation"] = data.pop("gpu_utilisation")
        data["cacheHealth"] = data.pop("cache_health")
        return cls(**data)

    class Config:
        populate_by_name = True


class CostEstimateRequest(BaseModel):
    frame_count: int = Field(..., gt=0)
    average_frame_time_ms: float = Field(..., gt=0)
    gpu_hourly_rate: float = Field(..., ge=0)
    gpu_count: int = Field(1, ge=1)
    render_hours: float = Field(0, ge=0)
    render_farm_hourly_rate: float = Field(0, ge=0)
    storage_gb: float = Field(0, ge=0)
    storage_rate_per_gb: float = Field(0, ge=0)
    data_egress_gb: float = Field(0, ge=0)
    egress_rate_per_gb: float = Field(0, ge=0)
    misc_costs: float = Field(0, ge=0)

    def to_entity(self) -> CostModelInput:
        return CostModelInput(**self.model_dump())


class CostEstimateModel(BaseModel):
    frame_count: int
    gpu_hours: float
    render_hours: float
    concurrency: int
    gpu_cost: float
    render_farm_cost: float
    storage_cost: float
    egress_cost: float
    misc_cost: float
    total_cost: float
    cost_per_frame: float

    @classmethod
    def from_breakdown(cls, breakdown: CostBreakdown) -> "CostEstimateModel":
        return cls(**breakdown.__dict__)


class RiskIndicatorModel(BaseModel):
    sequence: str
    shot_id: str
    risk_score: float
    render_time_ms: float
    error_rate: float
    cache_stability: float
    drivers: tuple[str, ...]

    @classmethod
    def from_entity(cls, indicator: RiskIndicator) -> "RiskIndicatorModel":
        return cls(**indicator.__dict__)


class PnLContributionModel(BaseModel):
    factor: str
    delta_cost: float
    percentage_points: float
    narrative: str

    @classmethod
    def from_entity(cls, contribution: PnLContribution) -> "PnLContributionModel":
        return cls(**contribution.__dict__)


class PnLBreakdownModel(BaseModel):
    baseline_cost: float
    current_cost: float
    delta_cost: float
    contributions: tuple[PnLContributionModel, ...]

    @classmethod
    def from_entity(cls, breakdown: PnLBreakdown) -> "PnLBreakdownModel":
        contributions = tuple(
            PnLContributionModel.from_entity(item) for item in breakdown.contributions
        )
        return cls(
            baseline_cost=breakdown.baseline_cost,
            current_cost=breakdown.current_cost,
            delta_cost=breakdown.delta_cost,
            contributions=contributions,
        )


class OptimizationScenarioRequest(BaseModel):
    name: str
    gpu_count: int | None = Field(None, ge=1)
    gpu_hourly_rate: float | None = Field(None, ge=0)
    frame_time_scale: float = Field(1.0, gt=0)
    resolution_scale: float = Field(1.0, gt=0)
    sampling_scale: float = Field(1.0, gt=0)
    notes: str | None = None

    def to_entity(self) -> OptimizationScenario:
        return OptimizationScenario(
            **{k: v for k, v in self.model_dump().items() if v is not None}
        )


class OptimizationResultModel(BaseModel):
    name: str
    total_cost: float
    cost_per_frame: float
    gpu_hours: float
    render_hours: float
    savings_vs_baseline: float
    notes: str

    @classmethod
    def from_entity(cls, result: OptimizationResult) -> "OptimizationResultModel":
        return cls(**result.__dict__)


class OptimizationBacktestRequest(BaseModel):
    scenarios: tuple[OptimizationScenarioRequest, ...] = Field(default_factory=tuple)


class OptimizationBacktestResponse(BaseModel):
    baseline: CostEstimateModel
    scenarios: tuple[OptimizationResultModel, ...]


class ShotLifecycleStageModel(BaseModel):
    name: str
    started_at: datetime
    completed_at: datetime | None
    duration_hours: float
    metrics: dict[str, Any]

    @classmethod
    def from_entity(cls, stage: ShotLifecycleStage) -> "ShotLifecycleStageModel":
        return cls(
            name=stage.name,
            started_at=stage.started_at,
            completed_at=stage.completed_at,
            duration_hours=stage.duration_hours,
            metrics=stage.metrics,
        )


class ShotLifecycleModel(BaseModel):
    sequence: str
    shot_id: str
    current_stage: str
    stages: tuple[ShotLifecycleStageModel, ...]

    @classmethod
    def from_entity(cls, lifecycle: ShotLifecycle) -> "ShotLifecycleModel":
        return cls(
            sequence=lifecycle.sequence,
            shot_id=lifecycle.shot_id,
            current_stage=lifecycle.current_stage,
            stages=tuple(
                ShotLifecycleStageModel.from_entity(stage) for stage in lifecycle.stages
            ),
        )


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health endpoint for uptime checks."""

    return {"status": "ok"}


@app.get("/render-feed", response_model=list[RenderMetricModel])
def render_feed(
    limit: int = Query(30, ge=1, le=250),
    engine: PeronaEngine = Depends(get_engine),
) -> list[RenderMetricModel]:
    """Return recent render telemetry samples for dashboard widgets."""

    metrics = [
        RenderMetricModel.from_entity(metric)
        for metric in engine.stream_render_metrics(limit)
    ]
    return metrics


@app.get("/render-feed/live")
async def render_feed_stream(
    limit: int = Query(30, ge=1, le=250),
    engine: PeronaEngine = Depends(get_engine),
) -> StreamingResponse:
    """Stream telemetry samples using newline delimited JSON."""

    async def _generator() -> Any:
        for metric in engine.stream_render_metrics(limit):
            model = RenderMetricModel.from_entity(metric)
            payload = model.model_dump(mode="json", by_alias=True)
            yield json.dumps(payload) + "\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(_generator(), media_type="application/x-ndjson")


@app.post("/cost/estimate", response_model=CostEstimateModel)
def cost_estimate(
    payload: CostEstimateRequest,
    engine: PeronaEngine = Depends(get_engine),
) -> CostEstimateModel:
    """Estimate the cost per frame for the supplied inputs."""

    breakdown = engine.estimate_cost(payload.to_entity())
    return CostEstimateModel.from_breakdown(breakdown)


@app.get("/risk-heatmap", response_model=list[RiskIndicatorModel])
def risk_heatmap(engine: PeronaEngine = Depends(get_engine)) -> list[RiskIndicatorModel]:
    """Return the current render risk heatmap."""

    return [RiskIndicatorModel.from_entity(item) for item in engine.risk_heatmap()]


@app.get("/pnl", response_model=PnLBreakdownModel)
def pnl(engine: PeronaEngine = Depends(get_engine)) -> PnLBreakdownModel:
    """Return the P&L attribution summary for the latest render window."""

    breakdown = engine.pnl_explainer()
    return PnLBreakdownModel.from_entity(breakdown)


@app.post("/optimization/backtest", response_model=OptimizationBacktestResponse)
def optimization_backtest(
    payload: OptimizationBacktestRequest,
    engine: PeronaEngine = Depends(get_engine),
) -> OptimizationBacktestResponse:
    """Run what-if optimisation scenarios and return their cost impact."""

    scenarios = [item.to_entity() for item in payload.scenarios]
    baseline, results = engine.run_optimization_backtest(scenarios)
    return OptimizationBacktestResponse(
        baseline=CostEstimateModel.from_breakdown(baseline),
        scenarios=tuple(OptimizationResultModel.from_entity(item) for item in results),
    )


@app.get("/shots/lifecycle", response_model=list[ShotLifecycleModel])
def shots_lifecycle(engine: PeronaEngine = Depends(get_engine)) -> list[ShotLifecycleModel]:
    """Return lifecycle timelines for key monitored shots."""

    return [ShotLifecycleModel.from_entity(item) for item in engine.shot_lifecycle()]


__all__ = ["app", "get_engine", "invalidate_engine_cache"]
