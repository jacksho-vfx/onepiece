"""Core data structures used by the Perona analytics engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from libraries.automation.render import optimization as render_optimization

SUPPORTED_CURRENCIES: Final[tuple[str, ...]] = ("GBP", "USD")
_CURRENCY_SYMBOLS: Final[dict[str, str]] = {"GBP": "£", "USD": "$"}
DEFAULT_CURRENCY: Final[str] = "GBP"


def _normalise_currency(value: object, fallback: str = DEFAULT_CURRENCY) -> str:
    """Return an upper-cased currency code when supported, else ``fallback``."""

    if isinstance(value, str):
        normalised = value.upper()
        if normalised in SUPPORTED_CURRENCIES:
            return normalised
    return fallback


def get_currency_symbol(currency: str) -> str:
    """Return the symbol representing *currency* or the code when unknown."""

    return _CURRENCY_SYMBOLS.get(currency, currency)


@dataclass(frozen=True)
class RenderMetric:
    """Single telemetry sample produced by the render farm."""

    sequence: str
    shot_id: str
    timestamp: datetime
    fps: float
    frame_time_ms: float
    error_count: int
    gpu_utilisation: float
    cache_health: float


@dataclass(frozen=True)
class CostModelInput:
    """Inputs required to estimate render costs."""

    frame_count: int
    average_frame_time_ms: float
    gpu_hourly_rate: float
    gpu_count: int = 1
    render_hours: float = 0.0
    render_farm_hourly_rate: float = 0.0
    storage_gb: float = 0.0
    storage_rate_per_gb: float = 0.0
    data_egress_gb: float = 0.0
    egress_rate_per_gb: float = 0.0
    misc_costs: float = 0.0
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _normalise_currency(self.currency))

    def to_library(self) -> render_optimization.CostModelInput:
        """Return the shared optimisation input representation."""

        return render_optimization.CostModelInput(
            frame_count=self.frame_count,
            average_frame_time_ms=self.average_frame_time_ms,
            gpu_hourly_rate=self.gpu_hourly_rate,
            gpu_count=self.gpu_count,
            render_hours=self.render_hours,
            render_farm_hourly_rate=self.render_farm_hourly_rate,
            storage_gb=self.storage_gb,
            storage_rate_per_gb=self.storage_rate_per_gb,
            data_egress_gb=self.data_egress_gb,
            egress_rate_per_gb=self.egress_rate_per_gb,
            misc_costs=self.misc_costs,
        )


@dataclass(frozen=True)
class CostBreakdown:
    """Detailed cost estimate for the requested parameters."""

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
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _normalise_currency(self.currency))

    @classmethod
    def from_library(
        cls, breakdown: render_optimization.CostBreakdown, *, currency: str
    ) -> "CostBreakdown":
        """Create a Perona breakdown from the shared optimisation result."""

        return cls(
            frame_count=breakdown.frame_count,
            gpu_hours=breakdown.gpu_hours,
            render_hours=breakdown.render_hours,
            concurrency=breakdown.concurrency,
            gpu_cost=breakdown.gpu_cost,
            render_farm_cost=breakdown.render_farm_cost,
            storage_cost=breakdown.storage_cost,
            egress_cost=breakdown.egress_cost,
            misc_cost=breakdown.misc_cost,
            total_cost=breakdown.total_cost,
            cost_per_frame=breakdown.cost_per_frame,
            currency=currency,
        )


@dataclass(frozen=True)
class ShotTelemetry:
    """Summary metrics used for risk calculations."""

    sequence: str
    shot_id: str
    average_frame_time_ms: float
    fps: float
    error_rate: float
    cache_stability: float
    frames_rendered: int
    deadline: datetime


@dataclass(frozen=True)
class RiskIndicator:
    """Risk score for a specific shot or sequence."""

    sequence: str
    shot_id: str
    risk_score: float
    render_time_ms: float
    error_rate: float
    cache_stability: float
    drivers: tuple[str, ...]


@dataclass(frozen=True)
class PnLContribution:
    """Contribution explaining the delta in spend versus the baseline."""

    factor: str
    delta_cost: float
    percentage_points: float
    narrative: str


@dataclass(frozen=True)
class PnLBreakdown:
    """Aggregate P&L attribution for the latest render window."""

    baseline_cost: float
    current_cost: float
    delta_cost: float
    contributions: tuple[PnLContribution, ...]


@dataclass(frozen=True)
class OptimizationScenario:
    """Parameters describing a what-if optimisation backtest."""

    name: str
    gpu_count: int | None = None
    gpu_hourly_rate: float | None = None
    frame_time_scale: float = 1.0
    resolution_scale: float = 1.0
    sampling_scale: float = 1.0
    notes: str = ""

    def to_library(self) -> render_optimization.OptimizationScenario:
        """Return the shared optimisation scenario representation."""

        return render_optimization.OptimizationScenario(
            name=self.name,
            gpu_count=self.gpu_count,
            gpu_hourly_rate=self.gpu_hourly_rate,
            frame_time_scale=self.frame_time_scale,
            resolution_scale=self.resolution_scale,
            sampling_scale=self.sampling_scale,
        )


@dataclass(frozen=True)
class OptimizationResult:
    """Result for a single optimisation scenario."""

    name: str
    total_cost: float
    cost_per_frame: float
    gpu_hours: float
    render_hours: float
    savings_vs_baseline: float
    savings_percent: float
    notes: str


@dataclass(frozen=True)
class ShotLifecycleStage:
    """Represents a production stage for a shot."""

    name: str
    started_at: datetime
    completed_at: datetime | None
    metrics: dict[str, float | str]

    @property
    def duration_hours(self) -> float:
        end = self.completed_at
        if end is None:
            if self.started_at.tzinfo is not None:
                end = datetime.now(self.started_at.tzinfo)
            else:
                end = datetime.utcnow()

        start = self.started_at
        if (start.tzinfo is None) != (end.tzinfo is None):
            if start.tzinfo is None:
                start = start.replace(tzinfo=end.tzinfo)
            else:
                end = end.replace(tzinfo=start.tzinfo)

        duration = (end - start).total_seconds() / 3600
        if duration < 0:
            duration = 0.0
        return round(duration, 2)


@dataclass(frozen=True)
class ShotLifecycle:
    """Lifecycle timeline for a shot."""

    sequence: str
    shot_id: str
    stages: tuple[ShotLifecycleStage, ...]

    @property
    def current_stage(self) -> str:
        for stage in reversed(self.stages):
            if stage.completed_at is None:
                return stage.name
        return self.stages[-1].name


__all__ = [
    "CostBreakdown",
    "CostModelInput",
    "DEFAULT_CURRENCY",
    "OptimizationResult",
    "OptimizationScenario",
    "PnLBreakdown",
    "PnLContribution",
    "RenderMetric",
    "RiskIndicator",
    "ShotLifecycle",
    "ShotLifecycleStage",
    "ShotTelemetry",
    "SUPPORTED_CURRENCIES",
    "get_currency_symbol",
]
