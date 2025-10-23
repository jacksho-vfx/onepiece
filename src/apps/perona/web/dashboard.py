"""FastAPI surface exposing Perona dashboard analytics."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from statistics import fmean
from threading import Lock
from typing import Any, Mapping, NamedTuple, Sequence

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from apps.perona.version import PERONA_VERSION

from apps.perona.engine import PeronaEngine, DEFAULT_SETTINGS_PATH
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
    SettingsSummary,
    sequences_from_lifecycles,
)
from apps.perona.models import Sequence as PeronaSequence


class RenderMetricBatch(BaseModel):
    """Payload wrapper for render metrics ingested via the API."""

    metrics: tuple[RenderMetric, ...] = Field(default_factory=tuple)

    model_config = ConfigDict(populate_by_name=True)

    def to_serialisable(self) -> list[dict[str, Any]]:
        """Return JSON-friendly dictionaries for persistence."""

        return [
            metric.model_dump(mode="json", by_alias=True) for metric in self.metrics
        ]


class RenderMetricStore:
    """Simple append-only store that persists render metrics to disk."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    def persist(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Append metrics to the backing store as NDJSON."""

        if not records:
            return

        lines = [
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            for record in records
        ]
        payload = "\n".join(lines) + "\n"

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(payload)


def _resolve_metrics_store_path() -> Path:
    """Return the configured metrics store path, falling back to cache dir."""

    env_path = os.getenv("PERONA_METRICS_PATH")
    if env_path:
        return Path(env_path).expanduser()

    cache_home = os.getenv("XDG_CACHE_HOME")
    base_dir = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return base_dir / "perona" / "render-metrics.ndjson"


app = FastAPI(
    title="Perona",
    description=(
        "Real-time VFX performance & cost dashboard inspired by quant trading systems. "
        "The API surfaces telemetry, risk scoring, cost attribution and optimisation "
        "backtests that power the interactive UI."
    ),
    version=PERONA_VERSION,
)


_metrics_store = RenderMetricStore(_resolve_metrics_store_path())


@app.post("/api/metrics", status_code=status.HTTP_202_ACCEPTED)
async def ingest_render_metrics(
    payload: RenderMetricBatch, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Accept render metrics and persist them asynchronously."""

    records = payload.to_serialisable()
    if not records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No metrics supplied."
        )

    background_tasks.add_task(_metrics_store.persist, records)
    return {"status": "accepted", "enqueued": len(records)}


class _EngineCacheEntry(NamedTuple):
    engine: PeronaEngine
    signature: tuple[str | None, str, float | None]
    settings_path: Path | None
    warnings: tuple[str, ...]


_engine_lock = Lock()
_engine_cache: _EngineCacheEntry | None = None


def _resolved_settings_path() -> Path | None:
    """Return the first existing settings candidate for display purposes."""

    env_path = os.getenv("PERONA_SETTINGS_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(DEFAULT_SETTINGS_PATH)

    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved
    return None


def _settings_signature() -> tuple[str | None, str, float | None]:
    """Return the cache signature for the current settings configuration."""

    env_path = os.getenv("PERONA_SETTINGS_PATH")
    resolved_path = _resolved_settings_path()
    signature_path = resolved_path or DEFAULT_SETTINGS_PATH.expanduser()

    mtime: float | None = None
    try:
        mtime = signature_path.stat().st_mtime
    except OSError:
        mtime = None

    return (env_path, str(signature_path), mtime)


def _get_engine_cache_entry(force_refresh: bool = False) -> _EngineCacheEntry:
    """Return the cached engine entry, refreshing when configuration changes."""

    global _engine_cache

    signature = _settings_signature()
    with _engine_lock:
        cache_entry = _engine_cache
        if force_refresh or cache_entry is None or cache_entry.signature != signature:
            load_result = PeronaEngine.from_settings()
            cache_entry = _EngineCacheEntry(
                engine=load_result.engine,
                signature=signature,
                settings_path=load_result.settings_path,
                warnings=load_result.warnings,
            )
            _engine_cache = cache_entry
        return cache_entry


def _load_engine(force_refresh: bool) -> PeronaEngine:
    """Return a cached engine instance, reloading when configuration changes."""

    return _get_engine_cache_entry(force_refresh).engine


def invalidate_engine_cache() -> None:
    """Clear the cached engine so it will be rebuilt on next use."""

    global _engine_cache
    with _engine_lock:
        _engine_cache = None


def _settings_summary_from_cache(force_refresh: bool = False) -> SettingsSummary:
    """Return a settings summary derived from the cached engine entry."""

    cache_entry = _get_engine_cache_entry(force_refresh)
    return SettingsSummary.from_engine(
        cache_entry.engine,
        settings_path=cache_entry.settings_path,
        warnings=cache_entry.warnings,
    )


def reload_settings() -> SettingsSummary:
    """Invalidate and rebuild the engine cache, returning the refreshed summary."""

    invalidate_engine_cache()
    return _settings_summary_from_cache(force_refresh=True)


def get_engine(refresh: bool = Query(False, alias="refresh_engine")) -> PeronaEngine:
    """FastAPI dependency yielding the shared Perona engine instance."""

    return _load_engine(refresh)


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health endpoint for uptime checks."""

    return {"status": "ok"}


@app.get("/settings", response_model=SettingsSummary)
def settings_summary() -> SettingsSummary:
    """Return the resolved configuration powering the dashboard."""

    return _settings_summary_from_cache()


@app.post("/settings/reload", response_model=SettingsSummary)
def settings_reload() -> SettingsSummary:
    """Reload engine configuration and return the updated settings summary."""

    return reload_settings()


@app.get("/render-feed", response_model=list[RenderMetric])
def render_feed(
    limit: int = Query(30, ge=1, le=250),
    sequence: str | None = Query(None),
    shot_id: str | None = Query(None),
    engine: PeronaEngine = Depends(get_engine),
) -> list[RenderMetric]:
    """Return recent render telemetry samples for dashboard widgets."""

    metrics = [
        RenderMetric.from_entity(metric)
        for metric in engine.stream_render_metrics(
            limit, sequence=sequence, shot_id=shot_id
        )
    ]
    return metrics


@app.get("/render-feed/live")
async def render_feed_stream(
    limit: int = Query(30, ge=1, le=250),
    sequence: str | None = Query(None),
    shot_id: str | None = Query(None),
    engine: PeronaEngine = Depends(get_engine),
) -> StreamingResponse:
    """Stream telemetry samples using newline delimited JSON."""

    async def _generator() -> Any:
        for metric in engine.stream_render_metrics(
            limit, sequence=sequence, shot_id=shot_id
        ):
            model = RenderMetric.from_entity(metric)
            payload = model.model_dump(mode="json", by_alias=True)
            yield json.dumps(payload) + "\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(_generator(), media_type="application/x-ndjson")


@app.get("/metrics")
def metrics_summary(engine: PeronaEngine = Depends(get_engine)) -> dict[str, Any]:
    """Return aggregated statistics for recent render telemetry."""

    samples = list(engine.stream_render_metrics())
    if not samples:
        return {
            "total_samples": 0,
            "averages": {
                "fps": 0.0,
                "frame_time_ms": 0.0,
                "gpu_utilisation": 0.0,
                "error_count": 0.0,
            },
            "sequences": [],
            "latest_sample": None,
        }

    def _rounded_mean(values: Sequence[float]) -> float:
        return round(fmean(values), 3)

    overall_averages = {
        "fps": _rounded_mean([sample.fps for sample in samples]),
        "frame_time_ms": _rounded_mean([sample.frame_time_ms for sample in samples]),
        "gpu_utilisation": _rounded_mean(
            [sample.gpu_utilisation for sample in samples]
        ),
        "error_count": _rounded_mean([sample.error_count for sample in samples]),
    }

    sequence_stats: dict[str, dict[str, Any]] = {}
    for sample in samples:
        entry = sequence_stats.setdefault(
            sample.sequence,
            {
                "shots": set(),
                "fps": [],
                "frame_time_ms": [],
                "gpu_utilisation": [],
                "error_count": [],
            },
        )
        entry["shots"].add(sample.shot_id)
        entry["fps"].append(sample.fps)
        entry["frame_time_ms"].append(sample.frame_time_ms)
        entry["gpu_utilisation"].append(sample.gpu_utilisation)
        entry["error_count"].append(sample.error_count)

    sequences_summary = [
        {
            "sequence": name,
            "shots": len(data["shots"]),
            "avg_fps": _rounded_mean(data["fps"]),
            "avg_frame_time_ms": _rounded_mean(data["frame_time_ms"]),
            "avg_gpu_utilisation": _rounded_mean(data["gpu_utilisation"]),
            "avg_error_count": _rounded_mean(data["error_count"]),
        }
        for name, data in sorted(sequence_stats.items())
    ]

    latest_sample = max(samples, key=lambda sample: sample.timestamp)
    latest_payload = RenderMetric.from_entity(latest_sample).model_dump(
        mode="json", by_alias=True
    )

    return {
        "total_samples": len(samples),
        "averages": overall_averages,
        "sequences": sequences_summary,
        "latest_sample": latest_payload,
    }


@app.post("/cost/estimate", response_model=CostEstimate)
def cost_estimate(
    payload: CostEstimateRequest,
    engine: PeronaEngine = Depends(get_engine),
) -> CostEstimate:
    """Estimate the cost per frame for the supplied inputs."""

    breakdown = engine.estimate_cost(payload.to_entity())
    return CostEstimate.from_breakdown(breakdown)


@app.get("/risk-heatmap", response_model=list[RiskIndicator])
def risk_heatmap(
    engine: PeronaEngine = Depends(get_engine),
) -> list[RiskIndicator]:
    """Return the current render risk heatmap."""

    return [RiskIndicator.from_entity(item) for item in engine.risk_heatmap()]


@app.get("/pnl", response_model=PnLBreakdown)
def pnl(engine: PeronaEngine = Depends(get_engine)) -> PnLBreakdown:
    """Return the P&L attribution summary for the latest render window."""

    breakdown = engine.pnl_explainer()
    return PnLBreakdown.from_entity(breakdown)


@app.post("/optimization/backtest", response_model=OptimizationBacktestResponse)
def optimization_backtest(
    payload: OptimizationBacktestRequest,
    engine: PeronaEngine = Depends(get_engine),
) -> OptimizationBacktestResponse:
    """Run what-if optimisation scenarios and return their cost impact."""

    scenarios = [item.to_entity() for item in payload.scenarios]
    baseline, results = engine.run_optimization_backtest(scenarios)
    return OptimizationBacktestResponse(
        baseline=CostEstimate.from_breakdown(baseline),
        scenarios=tuple(OptimizationResult.from_entity(item) for item in results),
    )


@app.get("/shots/lifecycle", response_model=list[Shot])
def shots_lifecycle(
    engine: PeronaEngine = Depends(get_engine),
) -> list[Shot]:
    """Return lifecycle timelines for key monitored shots."""

    return [Shot.from_entity(item) for item in engine.shot_lifecycle()]


@app.get("/shots/sequences", response_model=list[PeronaSequence])
def shot_sequences(
    engine: PeronaEngine = Depends(get_engine),
) -> list[PeronaSequence]:
    """Return monitored shots grouped by sequence."""

    sequences = sequences_from_lifecycles(engine.shot_lifecycle())
    return list(sequences)


@app.get("/shots")
def shots_summary(engine: PeronaEngine = Depends(get_engine)) -> dict[str, Any]:
    """Return aggregated production status for monitored shots."""

    lifecycles = list(engine.shot_lifecycle())
    total = len(lifecycles)
    completed = sum(
        1
        for lifecycle in lifecycles
        if all(stage.completed_at is not None for stage in lifecycle.stages)
    )

    by_stage = Counter(lifecycle.current_stage for lifecycle in lifecycles)
    by_sequence = Counter(lifecycle.sequence for lifecycle in lifecycles)

    active_shots: list[dict[str, Any]] = []
    for lifecycle in lifecycles:
        current_stage_name = lifecycle.current_stage
        stage_details = next(
            (stage for stage in lifecycle.stages if stage.name == current_stage_name),
            None,
        )
        active_shots.append(
            {
                "sequence": lifecycle.sequence,
                "shot_id": lifecycle.shot_id,
                "current_stage": current_stage_name,
                "stage_started_at": stage_details.started_at if stage_details else None,
                "stage_completed_at": (
                    stage_details.completed_at if stage_details else None
                ),
                "stage_metrics": dict(stage_details.metrics)
                if stage_details is not None
                else {},
            }
        )

    active_shots.sort(key=lambda item: (item["sequence"], item["shot_id"]))

    return {
        "total": total,
        "completed": completed,
        "active": max(total - completed, 0),
        "by_sequence": [
            {"name": name, "shots": count}
            for name, count in sorted(by_sequence.items())
        ],
        "by_stage": [
            {"name": name, "shots": count}
            for name, count in by_stage.most_common()
        ],
        "active_shots": active_shots,
    }


@app.get("/risk")
def risk_summary(engine: PeronaEngine = Depends(get_engine)) -> dict[str, Any]:
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


@app.get("/costs")
def costs_summary(engine: PeronaEngine = Depends(get_engine)) -> dict[str, Any]:
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

    return {
        "baseline": baseline_payload,
        "pnl": pnl_payload,
        "currency": baseline_breakdown.currency,
        "cost_per_frame": {
            "baseline": baseline_cost_per_frame,
            "current": current_cost_per_frame,
            "delta": delta_cost_per_frame,
        },
    }


@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket) -> None:
    """Stream render telemetry samples over a WebSocket connection."""

    await websocket.accept()
    try:
        while True:
            engine = _load_engine(False)
            for sample in engine.stream_render_metrics(limit=30):
                payload = RenderMetric.from_entity(sample).model_dump(
                    mode="json", by_alias=True
                )
                await websocket.send_json(payload)
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


__all__ = ["app", "get_engine", "invalidate_engine_cache", "reload_settings"]
