"""Wrangler scripts focused on operational scaling and optimisation."""

from __future__ import annotations

from typing import Any, Mapping

from apps.perona.web import dashboard as dashboard_module
from libraries.analytics.perona.engine import OptimizationScenario

from ..registry import WranglerScriptResult
from .telemetry import (
    _MIN_CONCURRENCY_RATIO,
    _TARGET_GPU_UTILISATION,
    _UTILISATION_TOLERANCE,
    _clamp,
)

_SPIN_DOWN_NOTES_PREFIX = (
    "Spin down idle workers to improve utilisation without starving the queue."
)


def _resolve_baseline_concurrency(engine: Any) -> int | None:
    baseline = getattr(engine, "baseline_cost_input", None)
    gpu_count = getattr(baseline, "gpu_count", None)
    if isinstance(gpu_count, (int, float)):
        resolved = int(gpu_count)
        if resolved > 0:
            return resolved
    return None


def _project_utilisation(current: float, *, baseline: int, proposed: int) -> float:
    if proposed <= 0 or baseline <= 0:
        return current
    projected = current * (baseline / proposed)
    return _clamp(projected, lower=0.0, upper=1.0)


def _run_spin_down_idle_workers_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    summary = dashboard_module.metrics_summary(engine=engine)

    averages = summary.get("averages") or {}
    average_utilisation = float(averages.get("gpu_utilisation", 0.0) or 0.0)
    baseline_concurrency = _resolve_baseline_concurrency(engine)

    target = _TARGET_GPU_UTILISATION
    tolerance = _UTILISATION_TOLERANCE
    band_lower = max(0.0, target - tolerance)
    band_upper = min(1.0, target + tolerance)

    if baseline_concurrency is None:
        message = (
            "Unable to determine the baseline GPU worker count; update Perona settings."
        )
        payload = {
            "current_utilisation": round(average_utilisation, 3),
            "baseline_worker_count": None,
            "recommended_worker_count": None,
            "target_band": {"lower": band_lower, "upper": band_upper},
            "projected_utilisation": None,
            "projected_savings": None,
            "notes": [
                "Baseline GPU configuration is missing, preventing a spin down recommendation.",
            ],
        }
        return WranglerScriptResult(
            script_id="spin_down_idle_workers",
            status="error",
            message=message,
            payload=payload,
        )

    notes: list[str] = []
    projected_savings: Mapping[str, Any] | None = None
    recommended_concurrency = baseline_concurrency

    if average_utilisation < band_lower:
        ratio = average_utilisation / target if target else 0.0
        ratio = _clamp(ratio, lower=_MIN_CONCURRENCY_RATIO, upper=1.0)
        recommended_concurrency = max(1, int(baseline_concurrency * ratio))
        if recommended_concurrency >= baseline_concurrency and baseline_concurrency > 1:
            recommended_concurrency = baseline_concurrency - 1

        projected_utilisation = _project_utilisation(
            average_utilisation,
            baseline=baseline_concurrency,
            proposed=recommended_concurrency,
        )
        notes.append(
            f"Projected utilisation after change: {projected_utilisation * 100:.1f}%"
        )
        if projected_utilisation > band_upper:
            notes.append(
                "Utilisation may briefly exceed the target band; monitor queue depth after scaling."
            )

        if recommended_concurrency < baseline_concurrency:
            scenario = OptimizationScenario(
                name=f"Scale to {recommended_concurrency} GPUs",
                gpu_count=recommended_concurrency,
                notes=_SPIN_DOWN_NOTES_PREFIX,
            )
            try:
                baseline_breakdown, results = engine.run_optimization_backtest(
                    [scenario]
                )
            except Exception as exc:  # pragma: no cover - defensive
                notes.append(f"Cost optimisation backtest failed: {exc}")
            else:
                if results:
                    result = results[0]
                    projected_savings = {
                        "amount": round(result.savings_vs_baseline, 2),
                        "percentage": round(result.savings_percent, 2),
                        "currency": getattr(baseline_breakdown, "currency", None),
                        "baseline_cost": round(baseline_breakdown.total_cost, 2),
                        "projected_cost": round(result.total_cost, 2),
                    }
                    if result.savings_vs_baseline <= 0:
                        notes.append(
                            "Backtest indicates limited savings; validate before committing to the change."
                        )
        else:
            projected_utilisation = average_utilisation
    else:
        projected_utilisation = average_utilisation
        notes.append(
            "Utilisation already sits within the target band; retain the current GPU allocation."
        )

    utilisation_pct = average_utilisation * 100
    lower_pct = band_lower * 100
    upper_pct = band_upper * 100

    if recommended_concurrency < baseline_concurrency:
        message = (
            f"GPU utilisation is {utilisation_pct:.1f}% — below the {lower_pct:.0f}-{upper_pct:.0f}% "
            f"target band. Recommend scaling workers from {baseline_concurrency} to "
            f"{recommended_concurrency}."
        )
    else:
        message = (
            f"GPU utilisation is {utilisation_pct:.1f}% and within the {lower_pct:.0f}-{upper_pct:.0f}% "
            "target band. No spin down recommended."
        )

    payload = {
        "current_utilisation": round(average_utilisation, 3),
        "baseline_worker_count": baseline_concurrency,
        "recommended_worker_count": recommended_concurrency,
        "target_band": {"lower": round(band_lower, 3), "upper": round(band_upper, 3)},
        "projected_utilisation": round(projected_utilisation, 3),
        "projected_savings": projected_savings,  # type: ignore[dict-item]
        "total_samples": int(summary.get("total_samples", 0) or 0),
        "notes": notes or [_SPIN_DOWN_NOTES_PREFIX],
    }

    return WranglerScriptResult(
        script_id="spin_down_idle_workers",
        status="success",
        message=message,
        payload=payload,
    )


__all__ = ["_run_spin_down_idle_workers_script"]
