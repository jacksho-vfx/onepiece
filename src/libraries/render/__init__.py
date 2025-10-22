"""Render farm submission adapters and analytics utilities."""

from .analytics import (
    average_frame_time_by_sequence,
    average_frame_time_by_shot,
    rolling_mean,
    total_cost_per_sequence,
    total_cost_per_shot,
)
from .base import RenderSubmissionError, SubmissionResult
from .optimization import (
    CostBreakdown,
    CostModelInput,
    OptimizationProjection,
    OptimizationScenario,
    estimate_cost,
    simulate_optimizations,
)

__all__ = [
    "RenderSubmissionError",
    "SubmissionResult",
    "average_frame_time_by_sequence",
    "average_frame_time_by_shot",
    "rolling_mean",
    "total_cost_per_sequence",
    "total_cost_per_shot",
    "CostModelInput",
    "CostBreakdown",
    "OptimizationScenario",
    "OptimizationProjection",
    "estimate_cost",
    "simulate_optimizations",
]
