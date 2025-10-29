"""Simulation helpers for render cost optimisation scenarios."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence


@dataclass(frozen=True)
class CostModelInput:
    """Inputs describing a render workload for cost estimation."""

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
    """Detailed cost estimate for a render workload."""

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
class OptimizationScenario:
    """Parameters describing an optimisation simulation."""

    name: str
    gpu_count: int | None = None
    gpu_hourly_rate: float | None = None
    frame_time_scale: float = 1.0
    resolution_scale: float = 1.0
    sampling_scale: float = 1.0


@dataclass(frozen=True)
class OptimizationProjection:
    """Outcome for a single optimisation simulation."""

    name: str
    breakdown: CostBreakdown
    savings: float
    savings_percent: float


def estimate_cost(inputs: CostModelInput) -> CostBreakdown:
    """Estimate the render cost for a set of model inputs."""

    if inputs.frame_count <= 0:
        raise ValueError("frame_count must be positive")
    if inputs.average_frame_time_ms <= 0:
        raise ValueError("average_frame_time_ms must be positive")
    if inputs.gpu_hourly_rate < 0:
        raise ValueError("gpu_hourly_rate cannot be negative")
    if inputs.gpu_count <= 0:
        raise ValueError("gpu_count must be positive")
    if inputs.render_farm_hourly_rate < 0:
        raise ValueError("render_farm_hourly_rate cannot be negative")
    if inputs.storage_rate_per_gb < 0:
        raise ValueError("storage_rate_per_gb cannot be negative")
    if inputs.egress_rate_per_gb < 0:
        raise ValueError("egress_rate_per_gb cannot be negative")

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

    total_cost = gpu_cost + render_farm_cost + storage_cost + egress_cost + misc_cost
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


def simulate_optimizations(
    baseline: CostModelInput, scenarios: Sequence[OptimizationScenario]
) -> tuple[CostBreakdown, tuple[OptimizationProjection, ...]]:
    """Simulate cost savings for the supplied optimisation ``scenarios``."""

    baseline_breakdown = estimate_cost(baseline)
    projections: list[OptimizationProjection] = []

    for scenario in scenarios:
        scenario_input = _apply_scenario(baseline, scenario)
        breakdown = estimate_cost(scenario_input)
        savings = round(baseline_breakdown.total_cost - breakdown.total_cost, 2)
        savings_percent = 0.0
        if baseline_breakdown.total_cost:
            savings_percent = round(savings / baseline_breakdown.total_cost * 100, 2)
        projections.append(
            OptimizationProjection(
                name=scenario.name,
                breakdown=breakdown,
                savings=savings,
                savings_percent=savings_percent,
            )
        )

    return baseline_breakdown, tuple(projections)


def _apply_scenario(
    baseline: CostModelInput, scenario: OptimizationScenario
) -> CostModelInput:
    """Return a new ``CostModelInput`` adjusted for ``scenario`` changes."""

    adjusted = replace(baseline)

    if scenario.gpu_count is not None:
        if scenario.gpu_count <= 0:
            raise ValueError("gpu_count must be positive when provided")
        adjusted = replace(adjusted, gpu_count=scenario.gpu_count)

    if scenario.gpu_hourly_rate is not None:
        if scenario.gpu_hourly_rate < 0:
            raise ValueError("gpu_hourly_rate cannot be negative")
        adjusted = replace(adjusted, gpu_hourly_rate=scenario.gpu_hourly_rate)

    frame_time_multiplier = max(
        scenario.frame_time_scale * scenario.sampling_scale, 0.05
    )
    adjusted = replace(
        adjusted,
        average_frame_time_ms=baseline.average_frame_time_ms * frame_time_multiplier,
        storage_gb=baseline.storage_gb * max(scenario.resolution_scale**2, 0.1),
    )

    return adjusted


@dataclass(frozen=True)
class FarmMetrics:
    """Snapshot of render farm health metrics used for heuristics."""

    queue_depth: int | None = None
    average_frame_time_ms: float | None = None


@dataclass(frozen=True)
class AdapterDefaults:
    """Adapter-specific defaults and limits for optimisation decisions."""

    default_priority: int
    priority_min: int | None = None
    priority_max: int | None = None
    default_chunk_size: int | None = None
    chunk_size_min: int | None = None
    chunk_size_max: int | None = None
    chunk_size_enabled: bool = False


@dataclass(frozen=True)
class SubmissionOptimizationDecision:
    """Recommended submission parameters derived from heuristics."""

    priority: int
    chunk_size: int | None
    reasons: tuple[str, ...]
    applied: bool


def compute_submission_adjustments(
    frame_count: int,
    defaults: AdapterDefaults,
    *,
    metrics: FarmMetrics | None = None,
) -> SubmissionOptimizationDecision:
    """Return heuristic recommendations for priority and chunk size.

    The function analyses *frame_count*, adapter ``defaults`` and the optional farm
    ``metrics`` snapshot to determine whether priority or chunk size should be
    nudged away from the adapter defaults.  The resulting decision tracks both the
    suggested values and the reasoning used to reach them.
    """

    if frame_count <= 0:
        raise ValueError("frame_count must be positive")

    metrics = metrics or FarmMetrics()

    priority = defaults.default_priority
    chunk_size = defaults.default_chunk_size if defaults.chunk_size_enabled else None
    reasons: list[str] = []

    # Priority adjustments based on frame span.
    if frame_count <= 10:
        boosted = priority + 10
        if boosted != priority:
            priority = boosted
            reasons.append("boosted priority for short frame range (<=10)")
    elif frame_count <= 50:
        boosted = priority + 5
        if boosted != priority:
            priority = boosted
            reasons.append("boosted priority for moderate frame range (<=50)")

    # Priority adjustments based on queue depth.
    if metrics.queue_depth is not None:
        if metrics.queue_depth >= 120:
            boosted = priority + 10
            if boosted != priority:
                priority = boosted
                reasons.append("raised priority for very high queue depth (>=120)")
        elif metrics.queue_depth >= 60:
            boosted = priority + 5
            if boosted != priority:
                priority = boosted
                reasons.append("raised priority for elevated queue depth (>=60)")
        elif metrics.queue_depth <= 10:
            lowered = priority - 5
            if lowered != priority:
                priority = lowered
                reasons.append("lowered priority for idle queue (<=10)")

    # Slightly prioritise very fast renders.
    if (
        metrics.average_frame_time_ms is not None
        and metrics.average_frame_time_ms <= 800
    ):
        boosted = priority + 3
        if boosted != priority:
            priority = boosted
            reasons.append("boosted priority for fast renders (<=800ms)")

    # Enforce adapter priority limits.
    if defaults.priority_min is not None and priority < defaults.priority_min:
        priority = defaults.priority_min
    if defaults.priority_max is not None and priority > defaults.priority_max:
        priority = defaults.priority_max

    # Chunk size adjustments require chunking support.
    if chunk_size is not None:
        min_chunk = (
            defaults.chunk_size_min if defaults.chunk_size_min is not None else 1
        )
        max_chunk = defaults.chunk_size_max

        # Clamp to supported range and avoid exceeding the frame span.
        chunk_size = max(min_chunk, chunk_size)
        if max_chunk is not None:
            chunk_size = min(chunk_size, max_chunk)
        chunk_size = min(chunk_size, frame_count)

        if frame_count <= 20:
            short_target = max(min_chunk, min(2, frame_count))
            if chunk_size > short_target:
                chunk_size = short_target
                reasons.append("reduced chunk size for short frame range (<=20)")
        elif frame_count >= 200:
            long_target = max(chunk_size, frame_count // 20)
            if max_chunk is not None:
                long_target = min(long_target, max_chunk)
            long_target = min(long_target, frame_count)
            if long_target > chunk_size:
                chunk_size = long_target
                reasons.append("increased chunk size for long frame range (>=200)")

        if (
            metrics.average_frame_time_ms is not None
            and metrics.average_frame_time_ms >= 4000
            and chunk_size > min_chunk
        ):
            slow_target = max(min_chunk, min(chunk_size, min(2, frame_count)))
            if chunk_size > slow_target:
                chunk_size = slow_target
                reasons.append("reduced chunk size for slow renders (>=4000ms)")

        if (
            metrics.queue_depth is not None
            and metrics.queue_depth >= 80
            and frame_count > 20
        ):
            busy_target = chunk_size + max(1, chunk_size // 2)
            busy_target = min(busy_target, frame_count)
            if max_chunk is not None:
                busy_target = min(busy_target, max_chunk)
            if busy_target > chunk_size:
                chunk_size = busy_target
                reasons.append("increased chunk size for busy farm (queue >=80)")

        chunk_size = max(min_chunk, chunk_size)
        if max_chunk is not None:
            chunk_size = min(chunk_size, max_chunk)
        chunk_size = min(chunk_size, frame_count)

    applied = priority != defaults.default_priority
    if defaults.chunk_size_enabled:
        applied = applied or chunk_size != defaults.default_chunk_size

    return SubmissionOptimizationDecision(
        priority=priority,
        chunk_size=chunk_size,
        reasons=tuple(reasons),
        applied=applied,
    )


__all__ = [
    "CostModelInput",
    "CostBreakdown",
    "OptimizationScenario",
    "OptimizationProjection",
    "estimate_cost",
    "simulate_optimizations",
    "FarmMetrics",
    "AdapterDefaults",
    "SubmissionOptimizationDecision",
    "compute_submission_adjustments",
]
