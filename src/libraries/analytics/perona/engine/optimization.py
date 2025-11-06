"""Helpers related to Perona optimisation scenarios."""

from __future__ import annotations

from .models import (
    CostBreakdown,
    CostModelInput,
    OptimizationScenario,
    get_currency_symbol,
)


def build_optimization_note(
    scenario: OptimizationScenario,
    breakdown: CostBreakdown,
    baseline: CostBreakdown,
    baseline_input: CostModelInput,
) -> str:
    """Compose a human readable summary for an optimisation projection."""

    delta = baseline.total_cost - breakdown.total_cost
    direction = "saves" if delta > 0 else "adds"
    symbol = get_currency_symbol(breakdown.currency)
    details: list[str] = [
        f"{direction} {symbol}{abs(delta):,.2f} vs baseline",
        f"cost/frame {breakdown.cost_per_frame:.4f}",
    ]
    if scenario.gpu_count and scenario.gpu_count != baseline.concurrency:
        details.append(f"gpu count -> {scenario.gpu_count}")
    if (
        scenario.gpu_hourly_rate
        and scenario.gpu_hourly_rate != baseline_input.gpu_hourly_rate
    ):
        details.append(f"gpu rate {symbol}{scenario.gpu_hourly_rate:.2f}/h")
    if scenario.frame_time_scale != 1.0 or scenario.sampling_scale != 1.0:
        details.append(
            f"frame time x{scenario.frame_time_scale * scenario.sampling_scale:.2f}"
        )
    if scenario.resolution_scale != 1.0:
        details.append(f"resolution x{scenario.resolution_scale:.2f}")
    return ", ".join(details)


__all__ = ["build_optimization_note"]
