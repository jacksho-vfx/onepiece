"""Domain logic backing the Perona VFX analytics dashboard."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence, Any
import tomllib


LOGGER = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class OptimizationResult:
    """Result for a single optimisation scenario."""

    name: str
    total_cost: float
    cost_per_frame: float
    gpu_hours: float
    render_hours: float
    savings_vs_baseline: float
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
        end = self.completed_at or datetime.utcnow()
        return round((end - self.started_at).total_seconds() / 3600, 2)


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


DEFAULT_BASELINE_COST_INPUT = CostModelInput(
    frame_count=2688,
    average_frame_time_ms=142.0,
    gpu_hourly_rate=8.75,
    gpu_count=64,
    render_hours=0.0,
    render_farm_hourly_rate=5.25,
    storage_gb=12.4,
    storage_rate_per_gb=0.38,
    data_egress_gb=3.8,
    egress_rate_per_gb=0.19,
    misc_costs=220.0,
)
DEFAULT_TARGET_ERROR_RATE = 0.012
DEFAULT_PNL_BASELINE_COST = 18240.0
DEFAULT_SETTINGS_PATH = Path(__file__).with_name("defaults.toml")


@dataclass(frozen=True)
class SettingsLoadResult:
    """Container describing the outcome of loading Perona settings."""

    engine: "PeronaEngine"
    settings_path: Path | None
    warnings: tuple[str, ...] = ()


def _load_settings(
    path: str | os.PathLike[str] | None,
) -> tuple[dict[str, object], Path | None, tuple[str, ...]]:
    """Load configuration data from a TOML file, falling back to defaults."""

    warnings: list[str] = []
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    env_path = os.getenv("PERONA_SETTINGS_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(DEFAULT_SETTINGS_PATH)

    for candidate in candidates:
        expanded = candidate.expanduser()
        try:
            with expanded.open("rb") as handle:
                return tomllib.load(handle), expanded, tuple(warnings)
        except FileNotFoundError as exc:
            message = (
                f"Settings file {expanded} not found ({exc}); falling back to defaults"
            )
            LOGGER.warning(message)
            warnings.append(message)
        except tomllib.TOMLDecodeError as exc:
            message = (
                f"Unable to parse settings file {expanded} ({exc}); falling back to defaults"
            )
            LOGGER.warning(message)
            warnings.append(message)
        except OSError as exc:
            message = (
                f"Unable to read settings file {expanded} ({exc}); falling back to defaults"
            )
            LOGGER.warning(message)
            warnings.append(message)
    return {}, None, tuple(warnings)


def _coerce_cost_model_input(
    data: Mapping[str, object] | None, fallback: CostModelInput
) -> CostModelInput:
    data = data or {}

    def _as_int(name: str, default: int) -> Any:
        value = data.get(name, default)
        try:
            return int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return default

    def _as_float(name: str, default: float) -> Any:
        value = data.get(name, default)
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    return CostModelInput(
        frame_count=_as_int("frame_count", fallback.frame_count),
        average_frame_time_ms=_as_float(
            "average_frame_time_ms", fallback.average_frame_time_ms
        ),
        gpu_hourly_rate=_as_float("gpu_hourly_rate", fallback.gpu_hourly_rate),
        gpu_count=_as_int("gpu_count", fallback.gpu_count),
        render_hours=_as_float("render_hours", fallback.render_hours),
        render_farm_hourly_rate=_as_float(
            "render_farm_hourly_rate", fallback.render_farm_hourly_rate
        ),
        storage_gb=_as_float("storage_gb", fallback.storage_gb),
        storage_rate_per_gb=_as_float(
            "storage_rate_per_gb", fallback.storage_rate_per_gb
        ),
        data_egress_gb=_as_float("data_egress_gb", fallback.data_egress_gb),
        egress_rate_per_gb=_as_float("egress_rate_per_gb", fallback.egress_rate_per_gb),
        misc_costs=_as_float("misc_costs", fallback.misc_costs),
    )


def _safe_float(value: object, default: float, *, setting: str) -> float:
    """Parse *value* as a float, returning *default* when invalid."""

    if value is None:
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        LOGGER.warning(
            "Ignoring invalid %s override %r; using default %s", setting, value, default
        )
        return default


class PeronaEngine:
    """High level orchestration of the dashboard analytics."""

    def __init__(
        self,
        baseline_input: CostModelInput | None = None,
        target_error_rate: float | None = None,
        pnl_baseline_cost: float | None = None,
    ) -> None:
        self._baseline_cost_input = baseline_input or DEFAULT_BASELINE_COST_INPUT
        self._target_error_rate = (
            target_error_rate
            if target_error_rate is not None
            else DEFAULT_TARGET_ERROR_RATE
        )
        self._pnl_baseline_cost = (
            pnl_baseline_cost
            if pnl_baseline_cost is not None
            else DEFAULT_PNL_BASELINE_COST
        )
        self._telemetry = self._build_telemetry()
        self._render_log = self._build_render_log()
        self._lifecycle = self._build_lifecycle()
        self._pnl_contributions = self._build_pnl_contributions()

    @property
    def baseline_cost_input(self) -> CostModelInput:
        return self._baseline_cost_input

    @property
    def target_error_rate(self) -> float:
        return self._target_error_rate

    @property
    def pnl_baseline_cost(self) -> float:
        return self._pnl_baseline_cost

    @classmethod
    def from_settings(
        cls, *, path: str | os.PathLike[str] | None = None
    ) -> SettingsLoadResult:
        """Instantiate the engine using configuration sourced from disk/env."""

        raw_settings, resolved_path, warnings = _load_settings(path)
        baseline_settings: Mapping[str, object] = raw_settings.get(
            "baseline_cost_input", {}
        )  # type: ignore[assignment]
        baseline_input = _coerce_cost_model_input(
            baseline_settings, DEFAULT_BASELINE_COST_INPUT
        )
        target_error_rate = _safe_float(
            raw_settings.get("target_error_rate"),
            DEFAULT_TARGET_ERROR_RATE,
            setting="target_error_rate",
        )
        pnl_baseline_cost = _safe_float(
            raw_settings.get("pnl_baseline_cost"),
            DEFAULT_PNL_BASELINE_COST,
            setting="pnl_baseline_cost",
        )
        engine = cls(
            baseline_input=baseline_input,
            target_error_rate=target_error_rate,
            pnl_baseline_cost=pnl_baseline_cost,
        )
        return SettingsLoadResult(
            engine=engine, settings_path=resolved_path, warnings=warnings
        )

    def stream_render_metrics(
        self,
        limit: int | None = None,
        *,
        sequence: str | None = None,
        shot_id: str | None = None,
    ) -> Iterable[RenderMetric]:
        """Return recent render metrics filtered by the supplied identifiers."""

        filtered: list[RenderMetric] = [
            sample
            for sample in self._render_log
            if (sequence is None or sample.sequence == sequence)
            and (shot_id is None or sample.shot_id == shot_id)
        ]
        if limit is not None:
            filtered = filtered[-limit:]
        for sample in filtered:
            yield sample

    def estimate_cost(self, inputs: CostModelInput) -> CostBreakdown:
        """Estimate the render costs for the supplied model inputs."""

        if inputs.frame_count <= 0:
            raise ValueError("frame_count must be positive")
        if inputs.average_frame_time_ms <= 0:
            raise ValueError("average_frame_time_ms must be positive")
        if inputs.gpu_hourly_rate < 0:
            raise ValueError("gpu_hourly_rate cannot be negative")

        frame_seconds = inputs.frame_count * inputs.average_frame_time_ms / 1000
        gpu_hours = frame_seconds / 3600
        concurrency = max(inputs.gpu_count, 1)
        theoretical_render_hours = frame_seconds / 3600 / concurrency
        render_hours = (
            inputs.render_hours if inputs.render_hours > 0 else theoretical_render_hours
        )
        gpu_cost = gpu_hours * inputs.gpu_hourly_rate
        render_farm_cost = render_hours * inputs.render_farm_hourly_rate
        storage_cost = inputs.storage_gb * inputs.storage_rate_per_gb
        egress_cost = inputs.data_egress_gb * inputs.egress_rate_per_gb
        misc_cost = inputs.misc_costs
        total_cost = (
            gpu_cost + render_farm_cost + storage_cost + egress_cost + misc_cost
        )
        cost_per_frame = total_cost / inputs.frame_count
        return CostBreakdown(
            frame_count=inputs.frame_count,
            gpu_hours=round(gpu_hours, 4),
            render_hours=round(render_hours, 4),
            concurrency=concurrency,
            gpu_cost=round(gpu_cost, 2),
            render_farm_cost=round(render_farm_cost, 2),
            storage_cost=round(storage_cost, 2),
            egress_cost=round(egress_cost, 2),
            misc_cost=round(misc_cost, 2),
            total_cost=round(total_cost, 2),
            cost_per_frame=round(cost_per_frame, 4),
        )

    def risk_heatmap(self) -> Sequence[RiskIndicator]:
        """Return risk scores ordered from most to least critical."""

        indicators: list[RiskIndicator] = []
        baseline_time = self._baseline_cost_input.average_frame_time_ms
        for telemetry in self._telemetry:
            render_factor = telemetry.average_frame_time_ms / baseline_time
            error_factor = telemetry.error_rate / self._target_error_rate
            cache_penalty = 1.0 - telemetry.cache_stability
            score = min(
                100.0,
                round(render_factor * 40 + error_factor * 40 + cache_penalty * 20, 2),
            )
            drivers: list[str] = []
            if render_factor > 1.05:
                drivers.append(
                    f"Slow renders (+{(render_factor - 1) * 100:.1f}% vs baseline)"
                )
            if error_factor > 1.0:
                drivers.append(
                    f"Error rate high (+{(error_factor - 1) * 100:.1f}% vs target)"
                )
            if cache_penalty > 0.2:
                drivers.append("Cache rebuild risk")
            if not drivers:
                drivers.append("Within tolerance")
            indicators.append(
                RiskIndicator(
                    sequence=telemetry.sequence,
                    shot_id=telemetry.shot_id,
                    risk_score=score,
                    render_time_ms=telemetry.average_frame_time_ms,
                    error_rate=telemetry.error_rate,
                    cache_stability=telemetry.cache_stability,
                    drivers=tuple(drivers),
                )
            )
        return tuple(sorted(indicators, key=lambda item: item.risk_score, reverse=True))

    def pnl_explainer(self) -> PnLBreakdown:
        """Explain the delta in render spend compared with the baseline."""

        baseline_cost = self._pnl_baseline_cost
        contributions = tuple(self._pnl_contributions)
        delta_cost = round(sum(item.delta_cost for item in contributions), 2)
        current_cost = round(baseline_cost + delta_cost, 2)
        return PnLBreakdown(
            baseline_cost=baseline_cost,
            current_cost=current_cost,
            delta_cost=delta_cost,
            contributions=contributions,
        )

    def run_optimization_backtest(
        self, scenarios: Sequence[OptimizationScenario]
    ) -> tuple[CostBreakdown, tuple[OptimizationResult, ...]]:
        """Simulate how different scenarios impact render cost and duration."""

        baseline_input = replace(self._baseline_cost_input)
        baseline_breakdown = self.estimate_cost(baseline_input)
        results: list[OptimizationResult] = []
        for scenario in scenarios:
            scenario_input = replace(baseline_input)
            if scenario.gpu_count is not None:
                scenario_input = replace(scenario_input, gpu_count=scenario.gpu_count)
            if scenario.gpu_hourly_rate is not None:
                scenario_input = replace(
                    scenario_input, gpu_hourly_rate=scenario.gpu_hourly_rate
                )
            frame_time_multiplier = max(
                scenario.frame_time_scale * scenario.sampling_scale, 0.05
            )
            scenario_input = replace(
                scenario_input,
                average_frame_time_ms=baseline_input.average_frame_time_ms
                * frame_time_multiplier,
                storage_gb=baseline_input.storage_gb
                * max(scenario.resolution_scale**2, 0.1),
            )
            breakdown = self.estimate_cost(scenario_input)
            savings = round(baseline_breakdown.total_cost - breakdown.total_cost, 2)
            notes = scenario.notes or self._build_optimization_note(
                scenario, breakdown, baseline_breakdown
            )
            results.append(
                OptimizationResult(
                    name=scenario.name,
                    total_cost=breakdown.total_cost,
                    cost_per_frame=breakdown.cost_per_frame,
                    gpu_hours=breakdown.gpu_hours,
                    render_hours=breakdown.render_hours,
                    savings_vs_baseline=savings,
                    notes=notes,
                )
            )
        return baseline_breakdown, tuple(results)

    def shot_lifecycle(self) -> Sequence[ShotLifecycle]:
        """Return lifecycle timelines for monitored shots."""

        return self._lifecycle

    def _build_telemetry(self) -> tuple[ShotTelemetry, ...]:
        return (
            ShotTelemetry(
                sequence="SQ12",
                shot_id="SQ12_SH010",
                average_frame_time_ms=168.0,
                fps=23.7,
                error_rate=0.028,
                cache_stability=0.71,
                frames_rendered=420,
            ),
            ShotTelemetry(
                sequence="SQ18",
                shot_id="SQ18_SH220",
                average_frame_time_ms=152.0,
                fps=24.0,
                error_rate=0.014,
                cache_stability=0.82,
                frames_rendered=512,
            ),
            ShotTelemetry(
                sequence="SQ05",
                shot_id="SQ05_SH045",
                average_frame_time_ms=139.0,
                fps=24.0,
                error_rate=0.009,
                cache_stability=0.9,
                frames_rendered=368,
            ),
            ShotTelemetry(
                sequence="SQ09",
                shot_id="SQ09_SH180",
                average_frame_time_ms=181.0,
                fps=23.5,
                error_rate=0.032,
                cache_stability=0.64,
                frames_rendered=488,
            ),
        )

    def _build_render_log(self) -> tuple[RenderMetric, ...]:
        base_time = datetime(2024, 5, 20, 8, 30)
        samples: list[RenderMetric] = []
        for index, telemetry in enumerate(self._telemetry):
            for offset in range(3):
                timestamp = base_time + timedelta(minutes=7 * index + 4 * offset)
                samples.append(
                    RenderMetric(
                        sequence=telemetry.sequence,
                        shot_id=telemetry.shot_id,
                        timestamp=timestamp,
                        fps=round(max(telemetry.fps - offset * 0.12, 18.0), 2),
                        frame_time_ms=round(
                            telemetry.average_frame_time_ms * (1 + 0.015 * offset), 2
                        ),
                        error_count=max(
                            0,
                            int(telemetry.error_rate * telemetry.frames_rendered * 0.5)
                            - offset,
                        ),
                        gpu_utilisation=round(
                            max(0.48, min(0.96, 0.62 + 0.05 * offset - index * 0.02)), 3
                        ),
                        cache_health=telemetry.cache_stability,
                    )
                )
        samples.sort(key=lambda metric: metric.timestamp)
        return tuple(samples)

    def _build_lifecycle(self) -> tuple[ShotLifecycle, ...]:
        base_day = datetime(2024, 5, 18, 9, 0)
        lifecycles: list[ShotLifecycle] = []
        lifecycles.append(
            ShotLifecycle(
                sequence="SQ12",
                shot_id="SQ12_SH010",
                stages=(
                    ShotLifecycleStage(
                        name="layout",
                        started_at=base_day - timedelta(days=12),
                        completed_at=base_day - timedelta(days=9, hours=3),
                        metrics={"owner": "D. Vega", "notes": "Hero creature blocking"},
                    ),
                    ShotLifecycleStage(
                        name="sim",
                        started_at=base_day - timedelta(days=9, hours=2),
                        completed_at=base_day - timedelta(days=4, hours=6),
                        metrics={"avg_cache_gb": 1.8, "resim_count": 4},
                    ),
                    ShotLifecycleStage(
                        name="lighting",
                        started_at=base_day - timedelta(days=4, hours=4),
                        completed_at=None,
                        metrics={"avg_render_time_ms": 168.0, "artist": "M. Chen"},
                    ),
                    ShotLifecycleStage(
                        name="comp",
                        started_at=base_day - timedelta(days=1),
                        completed_at=None,
                        metrics={"status": "Awaiting lighting caches"},
                    ),
                ),
            )
        )
        lifecycles.append(
            ShotLifecycle(
                sequence="SQ18",
                shot_id="SQ18_SH220",
                stages=(
                    ShotLifecycleStage(
                        name="layout",
                        started_at=base_day - timedelta(days=10),
                        completed_at=base_day - timedelta(days=7),
                        metrics={"owner": "P. Singh"},
                    ),
                    ShotLifecycleStage(
                        name="sim",
                        started_at=base_day - timedelta(days=7, hours=2),
                        completed_at=base_day - timedelta(days=3, hours=12),
                        metrics={"avg_cache_gb": 1.2, "resim_count": 2},
                    ),
                    ShotLifecycleStage(
                        name="lighting",
                        started_at=base_day - timedelta(days=3, hours=10),
                        completed_at=base_day - timedelta(days=1, hours=5),
                        metrics={"avg_render_time_ms": 152.0, "artist": "R. Ali"},
                    ),
                    ShotLifecycleStage(
                        name="comp",
                        started_at=base_day - timedelta(days=1, hours=4),
                        completed_at=None,
                        metrics={"status": "Review with supe"},
                    ),
                ),
            )
        )
        lifecycles.append(
            ShotLifecycle(
                sequence="SQ05",
                shot_id="SQ05_SH045",
                stages=(
                    ShotLifecycleStage(
                        name="layout",
                        started_at=base_day - timedelta(days=8),
                        completed_at=base_day - timedelta(days=6, hours=5),
                        metrics={"owner": "Y. Ito"},
                    ),
                    ShotLifecycleStage(
                        name="sim",
                        started_at=base_day - timedelta(days=6, hours=3),
                        completed_at=base_day - timedelta(days=5),
                        metrics={"avg_cache_gb": 0.9, "resim_count": 1},
                    ),
                    ShotLifecycleStage(
                        name="lighting",
                        started_at=base_day - timedelta(days=5, hours=2),
                        completed_at=base_day - timedelta(days=2),
                        metrics={"avg_render_time_ms": 139.0, "artist": "K. Lopez"},
                    ),
                    ShotLifecycleStage(
                        name="comp",
                        started_at=base_day - timedelta(days=2, hours=1),
                        completed_at=base_day - timedelta(hours=18),
                        metrics={"status": "Final"},
                    ),
                ),
            )
        )
        lifecycles.append(
            ShotLifecycle(
                sequence="SQ09",
                shot_id="SQ09_SH180",
                stages=(
                    ShotLifecycleStage(
                        name="layout",
                        started_at=base_day - timedelta(days=14),
                        completed_at=base_day - timedelta(days=11, hours=6),
                        metrics={"owner": "N. Wolfe"},
                    ),
                    ShotLifecycleStage(
                        name="sim",
                        started_at=base_day - timedelta(days=11, hours=5),
                        completed_at=base_day - timedelta(days=6),
                        metrics={"avg_cache_gb": 2.4, "resim_count": 6},
                    ),
                    ShotLifecycleStage(
                        name="lighting",
                        started_at=base_day - timedelta(days=6, hours=2),
                        completed_at=None,
                        metrics={"avg_render_time_ms": 181.0, "artist": "C. Ramos"},
                    ),
                    ShotLifecycleStage(
                        name="comp",
                        started_at=base_day - timedelta(days=2, hours=12),
                        completed_at=None,
                        metrics={"status": "Temp slap"},
                    ),
                ),
            )
        )
        return tuple(lifecycles)

    def _build_pnl_contributions(self) -> tuple[PnLContribution, ...]:
        return (
            PnLContribution(
                factor="Lighting complexity",
                delta_cost=920.0,
                percentage_points=10.4,
                narrative="Additional volumetric bounce passes increased light cache time",
            ),
            PnLContribution(
                factor="Volumetric FX iterations",
                delta_cost=610.0,
                percentage_points=6.8,
                narrative="Two extra nebula simulations pushed GPU occupancy",
            ),
            PnLContribution(
                factor="Cache rebuilds",
                delta_cost=280.0,
                percentage_points=3.1,
                narrative="Downstream layout updates invalidated lighting caches",
            ),
            PnLContribution(
                factor="GPU spot rate drift",
                delta_cost=-350.0,
                percentage_points=-3.9,
                narrative="Night renders benefited from lower spot pricing",
            ),
            PnLContribution(
                factor="Farm occupancy",
                delta_cost=-120.0,
                percentage_points=-1.4,
                narrative="Better queue packing reduced idle nodes",
            ),
        )

    def _build_optimization_note(
        self,
        scenario: OptimizationScenario,
        breakdown: CostBreakdown,
        baseline: CostBreakdown,
    ) -> str:
        delta = baseline.total_cost - breakdown.total_cost
        direction = "saves" if delta > 0 else "adds"
        details: list[str] = [
            f"{direction} ${abs(delta):,.2f} vs baseline",
            f"cost/frame {breakdown.cost_per_frame:.4f}",
        ]
        if scenario.gpu_count and scenario.gpu_count != baseline.concurrency:
            details.append(f"gpu count -> {scenario.gpu_count}")
        if (
            scenario.gpu_hourly_rate
            and scenario.gpu_hourly_rate != self._baseline_cost_input.gpu_hourly_rate
        ):
            details.append(f"gpu rate ${scenario.gpu_hourly_rate:.2f}/h")
        if scenario.frame_time_scale != 1.0 or scenario.sampling_scale != 1.0:
            details.append(
                f"frame time x{scenario.frame_time_scale * scenario.sampling_scale:.2f}"
            )
        if scenario.resolution_scale != 1.0:
            details.append(f"resolution x{scenario.resolution_scale:.2f}")
        return ", ".join(details)


__all__ = [
    "CostBreakdown",
    "CostModelInput",
    "OptimizationResult",
    "OptimizationScenario",
    "PeronaEngine",
    "PnLBreakdown",
    "PnLContribution",
    "RenderMetric",
    "RiskIndicator",
    "ShotLifecycle",
    "ShotLifecycleStage",
]
