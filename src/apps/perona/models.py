"""Shared Pydantic models exposed by the Perona API."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from .engine import (
    CostBreakdown,
    CostModelInput,
    OptimizationResult as EngineOptimizationResult,
    OptimizationScenario,
    PnLBreakdown as EnginePnLBreakdown,
    PnLContribution as EnginePnLContribution,
    RenderMetric as EngineRenderMetric,
    RiskIndicator as EngineRiskIndicator,
    ShotLifecycle,
    ShotLifecycleStage,
)


class RenderMetric(BaseModel):
    """Telemetry sample produced by the render farm."""

    sequence: str
    shot_id: str
    timestamp: datetime
    fps: float
    frame_time_ms: float
    error_count: int
    gpu_utilisation: float = Field(..., alias="gpuUtilisation")
    cache_health: float = Field(..., alias="cacheHealth")

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_entity(cls, metric: EngineRenderMetric) -> "RenderMetric":
        """Create a serialisable model from :class:`~apps.perona.engine.RenderMetric`."""

        return cls(
            sequence=metric.sequence,
            shot_id=metric.shot_id,
            timestamp=metric.timestamp,
            fps=metric.fps,
            frame_time_ms=metric.frame_time_ms,
            error_count=metric.error_count,
            gpu_utilisation=metric.gpu_utilisation,
            cache_health=metric.cache_health,
        )


class CostEstimate(BaseModel):
    """Detailed cost estimate for render inputs."""

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
    def from_breakdown(cls, breakdown: CostBreakdown) -> "CostEstimate":
        """Create a serialisable model from :class:`~apps.perona.engine.CostBreakdown`."""

        return cls(**breakdown.__dict__)


class RiskIndicator(BaseModel):
    """Risk score for a particular shot."""

    sequence: str
    shot_id: str
    risk_score: float
    render_time_ms: float
    error_rate: float
    cache_stability: float
    drivers: tuple[str, ...]

    @classmethod
    def from_entity(cls, indicator: EngineRiskIndicator) -> "RiskIndicator":
        return cls(**indicator.__dict__)


class PnLContribution(BaseModel):
    """Contribution to the change in render spend."""

    factor: str
    delta_cost: float
    percentage_points: float
    narrative: str

    @classmethod
    def from_entity(cls, contribution: EnginePnLContribution) -> "PnLContribution":
        return cls(**contribution.__dict__)


class PnLBreakdown(BaseModel):
    """Summary of the baseline and current render spend."""

    baseline_cost: float
    current_cost: float
    delta_cost: float
    contributions: tuple[PnLContribution, ...]

    @classmethod
    def from_entity(cls, breakdown: EnginePnLBreakdown) -> "PnLBreakdown":
        contributions = tuple(
            PnLContribution.from_entity(item) for item in breakdown.contributions
        )
        return cls(
            baseline_cost=breakdown.baseline_cost,
            current_cost=breakdown.current_cost,
            delta_cost=breakdown.delta_cost,
            contributions=contributions,
        )


class OptimizationResult(BaseModel):
    """Result of a single optimisation scenario."""

    name: str
    total_cost: float
    cost_per_frame: float
    gpu_hours: float
    render_hours: float
    savings_vs_baseline: float
    notes: str

    @classmethod
    def from_entity(cls, result: EngineOptimizationResult) -> "OptimizationResult":
        return cls(**result.__dict__)


class ShotStage(BaseModel):
    """Representation of an individual stage within a shot lifecycle."""

    name: str
    started_at: datetime
    completed_at: datetime | None
    duration_hours: float
    metrics: dict[str, Any]

    @classmethod
    def from_entity(cls, stage: ShotLifecycleStage) -> "ShotStage":
        return cls(
            name=stage.name,
            started_at=stage.started_at,
            completed_at=stage.completed_at,
            duration_hours=stage.duration_hours,
            metrics=dict(stage.metrics),
        )


class Shot(BaseModel):
    """Lifecycle summary for a shot."""

    sequence: str
    shot_id: str
    current_stage: str
    stages: tuple[ShotStage, ...]

    @classmethod
    def from_entity(cls, lifecycle: ShotLifecycle) -> "Shot":
        return cls(
            sequence=lifecycle.sequence,
            shot_id=lifecycle.shot_id,
            current_stage=lifecycle.current_stage,
            stages=tuple(ShotStage.from_entity(stage) for stage in lifecycle.stages),
        )


class Sequence(BaseModel):
    """Collection of shots that belong to the same sequence."""

    name: str
    shots: tuple[Shot, ...] = Field(default_factory=tuple)

    @classmethod
    def from_shots(cls, name: str, shots: Iterable[Shot]) -> "Sequence":
        ordered = tuple(sorted(shots, key=lambda shot: shot.shot_id))
        return cls(name=name, shots=ordered)


class CostEstimateRequest(BaseModel):
    """Payload accepted by the cost estimate endpoint."""

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


class OptimizationScenarioRequest(BaseModel):
    """Payload describing a what-if optimisation scenario."""

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


class OptimizationBacktestRequest(BaseModel):
    """Container for optimisation scenarios supplied by the client."""

    scenarios: tuple[OptimizationScenarioRequest, ...] = Field(default_factory=tuple)


class OptimizationBacktestResponse(BaseModel):
    """Response returned by the optimisation backtest endpoint."""

    baseline: CostEstimate
    scenarios: tuple[OptimizationResult, ...]


def shots_from_lifecycles(lifecycles: Iterable[ShotLifecycle]) -> tuple[Shot, ...]:
    """Convert engine lifecycles to serialisable shot models."""

    return tuple(Shot.from_entity(item) for item in lifecycles)


def sequences_from_lifecycles(
    lifecycles: Iterable[ShotLifecycle],
) -> tuple[Sequence, ...]:
    """Group lifecycles by sequence and return serialisable models."""

    grouped: dict[str, list[Shot]] = defaultdict(list)
    for lifecycle in lifecycles:
        shot = Shot.from_entity(lifecycle)
        grouped[shot.sequence].append(shot)
    return tuple(
        Sequence.from_shots(sequence, shots)
        for sequence, shots in sorted(grouped.items(), key=lambda item: item[0])
    )


__all__ = [
    "CostEstimate",
    "CostEstimateRequest",
    "OptimizationBacktestRequest",
    "OptimizationBacktestResponse",
    "OptimizationResult",
    "OptimizationScenarioRequest",
    "PnLBreakdown",
    "PnLContribution",
    "RenderMetric",
    "RiskIndicator",
    "Sequence",
    "Shot",
    "ShotStage",
    "shots_from_lifecycles",
    "sequences_from_lifecycles",
]
