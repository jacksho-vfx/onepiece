"""Wrangler scripts focused on cost and financial insights."""

from __future__ import annotations

import math
from typing import Any

from apps.perona.web import dashboard as dashboard_module
from libraries.analytics.perona.engine.models import (
    OptimizationScenario,
    get_currency_symbol,
)

from ..registry import WranglerScriptResult


def _run_analyse_cost_drivers_script() -> WranglerScriptResult:
    """Summarise the leading cost drivers and proposed remediations."""

    engine = dashboard_module.get_engine()
    statistics, recommendations = engine.cost_insights(top_n=5)

    recommended_actions = list(recommendations)

    if not statistics:
        message = (
            "Cost driver insights are unavailable; ingest telemetry before retrying."
        )
        return WranglerScriptResult(
            script_id="analyse_cost_drivers",
            status="error",
            message=message,
            payload={
                "headline": message,
                "top_features": [],
                "recommended_actions": recommended_actions,
            },
        )

    def _feature_delta(entry: Any) -> float:
        try:
            return float(entry.maximum) - float(entry.minimum)
        except Exception:  # pragma: no cover - defensive fallback
            return 0.0

    sorted_stats = sorted(statistics, key=_feature_delta, reverse=True)
    top_features: list[dict[str, Any]] = []
    for entry in sorted_stats[:5]:
        delta = _feature_delta(entry)
        top_features.append(
            {
                "feature": getattr(entry, "name", None),
                "mean": round(float(getattr(entry, "mean", 0.0) or 0.0), 3),
                "stddev": round(float(getattr(entry, "stddev", 0.0) or 0.0), 3),
                "minimum": round(float(getattr(entry, "minimum", 0.0) or 0.0), 3),
                "maximum": round(float(getattr(entry, "maximum", 0.0) or 0.0), 3),
                "delta": round(delta, 3),
            }
        )

    leader = top_features[0]
    headline = (
        f"{leader['feature']} spans {leader['delta']:.3f} between observed min/max "
        "cost inputs — address the top drivers to stabilise spend."
    )

    payload = {
        "headline": headline,
        "top_features": top_features,
        "recommended_actions": recommended_actions,
    }

    return WranglerScriptResult(
        script_id="analyse_cost_drivers",
        status="success",
        message=headline,
        payload=payload,
    )


def _run_explain_pnl_delta_script() -> WranglerScriptResult:
    """Summarise how current render spend deviates from the baseline."""

    engine = dashboard_module.get_engine()
    baseline_input = getattr(engine, "baseline_cost_input", None)
    if baseline_input is None:
        message = (
            "Baseline cost input unavailable; configure Perona settings before "
            "explaining the P&L delta."
        )
        return WranglerScriptResult(
            script_id="explain_pnl_delta",
            status="error",
            message=message,
            payload=None,
        )

    breakdown = engine.pnl_explainer()
    baseline_breakdown = engine.estimate_cost(baseline_input)

    frame_count = max(getattr(baseline_breakdown, "frame_count", 0) or 0, 1)
    baseline_total = round(float(baseline_breakdown.total_cost), 2)
    current_total = round(float(breakdown.current_cost), 2)
    delta_total = round(float(breakdown.delta_cost), 2)
    currency = getattr(baseline_breakdown, "currency", None)

    baseline_cost_per_frame = round(float(baseline_breakdown.cost_per_frame), 4)
    current_cost_per_frame = round(current_total / frame_count, 4)
    delta_cost_per_frame = round(current_cost_per_frame - baseline_cost_per_frame, 4)

    contributions = sorted(
        getattr(breakdown, "contributions", ()),
        key=lambda item: abs(getattr(item, "delta_cost", 0.0)),
        reverse=True,
    )

    ranked_contributions: list[dict[str, Any]] = []
    for index, contribution in enumerate(contributions[:3], start=1):
        ranked_contributions.append(
            {
                "rank": index,
                "factor": getattr(contribution, "factor", None),
                "delta_cost": round(float(getattr(contribution, "delta_cost", 0.0)), 2),
                "percentage_points": round(
                    float(getattr(contribution, "percentage_points", 0.0)), 2
                ),
                "narrative": getattr(contribution, "narrative", None),
            }
        )

    formatted_delta = f"{delta_total:+.2f}"
    formatted_leader_delta: str | None = None
    if currency:
        formatted_delta = f"{currency} {formatted_delta}"

    if ranked_contributions:
        leader = ranked_contributions[0]
        formatted_leader_delta = f"{leader['delta_cost']:+.2f}"
        if currency:
            formatted_leader_delta = f"{currency} {formatted_leader_delta}"
        message = (
            "Render spend delta "
            f"{formatted_delta} vs baseline; leading factor: {leader['factor']}"
        )
        if formatted_leader_delta is not None:
            message += f" ({formatted_leader_delta})."
        else:
            message += "."
    else:
        message = (
            f"Render spend delta {formatted_delta} vs baseline; "
            "no contribution data available."
        )

    payload = {
        "totals": {
            "baseline": baseline_total,
            "current": current_total,
            "delta": delta_total,
            "currency": currency,
        },
        "per_frame": {
            "baseline": baseline_cost_per_frame,
            "current": current_cost_per_frame,
            "delta": delta_cost_per_frame,
        },
        "frame_count": frame_count,
        "contributions": ranked_contributions,
    }

    return WranglerScriptResult(
        script_id="explain_pnl_delta",
        status="success",
        message=message,
        payload=payload,
    )


def _run_evaluate_optimisation_playbook_script() -> WranglerScriptResult:
    """Run a small optimisation playbook and surface the best savings."""

    engine = dashboard_module.get_engine()
    baseline_input = getattr(engine, "baseline_cost_input", None)
    if baseline_input is None:
        message = (
            "Baseline configuration unavailable; configure Perona cost inputs before "
            "evaluating the optimisation playbook."
        )
        return WranglerScriptResult(
            script_id="evaluate_optimisation_playbook",
            status="error",
            message=message,
            payload=None,
        )

    scenarios: list[OptimizationScenario] = []

    baseline_gpu_count = getattr(baseline_input, "gpu_count", None)
    concurrency_target: int | None = None
    if isinstance(baseline_gpu_count, (int, float)):
        baseline_gpu_count = int(baseline_gpu_count)
        if baseline_gpu_count > 0:
            concurrency_target = max(1, math.floor(baseline_gpu_count * 0.8))
            if concurrency_target == baseline_gpu_count and baseline_gpu_count > 1:
                concurrency_target = baseline_gpu_count - 1

    if concurrency_target is not None:
        concurrency_label = "GPU" if concurrency_target == 1 else "GPUs"
        scenarios.append(
            OptimizationScenario(
                name=f"Reduce concurrency to {concurrency_target} {concurrency_label}",
                gpu_count=concurrency_target,
                notes="Scale back GPU workers to lift utilisation without starving jobs.",
            )
        )
    else:
        scenarios.append(
            OptimizationScenario(
                name="Reduce concurrency by 20%",
                gpu_count=1,
                notes="Fallback concurrency reduction when baseline is unavailable.",
            )
        )

    baseline_gpu_rate = getattr(baseline_input, "gpu_hourly_rate", None)
    if isinstance(baseline_gpu_rate, (int, float)) and baseline_gpu_rate > 0:
        discounted_rate = round(float(baseline_gpu_rate) * 0.85, 2)
    else:
        discounted_rate = None
    scenarios.append(
        OptimizationScenario(
            name="Negotiate 15% cheaper GPU rate",
            gpu_hourly_rate=discounted_rate,
            notes="Model a vendor discount on hourly GPU pricing.",
        )
    )

    scenarios.append(
        OptimizationScenario(
            name="Dial back sampling by 10%",
            frame_time_scale=0.9,
            sampling_scale=0.9,
            notes="Lower sampling and quality dials to shorten render times.",
        )
    )

    try:
        baseline_breakdown, results = engine.run_optimization_backtest(scenarios)
    except Exception as exc:  # pragma: no cover - defensive fallback
        message = f"Optimisation backtest failed: {exc}"
        return WranglerScriptResult(
            script_id="evaluate_optimisation_playbook",
            status="error",
            message=message,
            payload=None,
        )

    sorted_results = sorted(
        results, key=lambda item: item.savings_vs_baseline, reverse=True
    )

    baseline_payload = {
        "frame_count": baseline_breakdown.frame_count,
        "total_cost": round(baseline_breakdown.total_cost, 2),
        "cost_per_frame": round(baseline_breakdown.cost_per_frame, 4),
        "render_hours": round(baseline_breakdown.render_hours, 2),
        "gpu_hours": round(baseline_breakdown.gpu_hours, 2),
        "concurrency": baseline_breakdown.concurrency,
        "currency": baseline_breakdown.currency,
    }

    scenarios_payload: list[dict[str, Any]] = []
    for result in sorted_results:
        scenarios_payload.append(
            {
                "name": result.name,
                "total_cost": round(result.total_cost, 2),
                "render_hours": round(result.render_hours, 2),
                "gpu_hours": round(result.gpu_hours, 2),
                "savings": {
                    "amount": round(result.savings_vs_baseline, 2),
                    "percent": round(result.savings_percent, 2),
                },
                "notes": result.notes,
            }
        )

    currency_symbol = get_currency_symbol(baseline_breakdown.currency)

    if scenarios_payload:
        leader = scenarios_payload[0]
        amount = leader["savings"]["amount"]
        percent = leader["savings"]["percent"]
        percent_text = f"{percent:+.2f}%"
        if amount > 0:
            message = (
                "Top optimisation win: "
                f"{leader['name']} could save {currency_symbol}{amount:,.2f} "
                f"({percent_text})."
            )
        else:
            message = (
                "Optimisation playbook evaluated; no savings projected. "
                f"Best option {leader['name']} changes spend by "
                f"{currency_symbol}{abs(amount):,.2f} ({percent_text})."
            )
    else:
        message = (
            "Optimisation playbook evaluated; unable to compute scenario outcomes."
        )

    payload = {
        "baseline": baseline_payload,
        "scenarios": scenarios_payload,
    }

    return WranglerScriptResult(
        script_id="evaluate_optimisation_playbook",
        status="success",
        message=message,
        payload=payload,
    )


__all__ = [
    "_run_analyse_cost_drivers_script",
    "_run_explain_pnl_delta_script",
    "_run_evaluate_optimisation_playbook_script",
]
