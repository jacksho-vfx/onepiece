"""Helpers for producing P&L narratives for the Perona dashboard."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence, Tuple


@dataclass(frozen=True)
class CostDriverDelta:
    """Represents how a single driver influences render cost deltas."""

    name: str
    metric_change_pct: float
    cost_delta: float
    metric_label: str | None = None
    cost_label: str = "cost"

    def metric_change_display(self, *, precision: int = 1) -> str:
        """Return a human friendly representation of the metric shift."""

        return _format_percentage(self.metric_change_pct, precision=precision)

    def cost_change_pct(self, baseline_cost: float) -> float:
        """Return the cost delta expressed as percentage of ``baseline_cost``."""

        if baseline_cost == 0:
            if self.cost_delta == 0:
                return 0.0
            return math.copysign(math.inf, self.cost_delta)
        return (self.cost_delta / baseline_cost) * 100.0

    def cost_change_display(self, baseline_cost: float, *, precision: int = 1) -> str:
        """Return a human friendly representation of the cost impact."""

        return _format_percentage(
            self.cost_change_pct(baseline_cost), precision=precision
        )

    def describe(self, baseline_cost: float, *, precision: int = 1) -> str:
        """Describe the driver using the "metric → cost" narrative."""

        metric = self.metric_label or self.name
        metric_part = self.metric_change_display(precision=precision)
        cost_part = self.cost_change_display(baseline_cost, precision=precision)
        return f"{metric} {metric_part} → {self.cost_label} {cost_part}"


def total_cost_delta(deltas: Iterable[CostDriverDelta]) -> float:
    """Return the sum of ``cost_delta`` values, rounded to cents."""

    return round(sum(delta.cost_delta for delta in deltas), 2)


def summarise_cost_deltas(
    baseline_cost: float,
    deltas: Sequence[CostDriverDelta],
    *,
    precision: int = 1,
) -> Tuple[str, ...]:
    """Return formatted narratives for each cost driver delta."""

    return tuple(delta.describe(baseline_cost, precision=precision) for delta in deltas)


def _format_percentage(value: float, *, precision: int) -> str:
    """Format ``value`` (expressed in percentage points) using arrow notation."""

    if math.isnan(value):
        return "→0%"
    if math.isinf(value):
        arrow = "↑" if value > 0 else "↓"
        return f"{arrow}∞"
    arrow = "↑" if value > 0 else "↓" if value < 0 else "→"
    magnitude = round(abs(value), precision)
    formatted = f"{magnitude:.{precision}f}" if precision > 0 else f"{int(magnitude)}"
    if precision > 0:
        formatted = formatted.rstrip("0").rstrip(".")
    if not formatted:
        formatted = "0"
    return f"{arrow}{formatted}%"


__all__ = [
    "CostDriverDelta",
    "summarise_cost_deltas",
    "total_cost_delta",
]
