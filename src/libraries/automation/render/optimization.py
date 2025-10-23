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


__all__ = [
    "CostModelInput",
    "CostBreakdown",
    "OptimizationScenario",
    "OptimizationProjection",
    "estimate_cost",
    "simulate_optimizations",
]
