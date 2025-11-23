"""Domain logic backing the Perona VFX analytics dashboard."""

from __future__ import annotations

import logging
import math
import os
import statistics
from dataclasses import replace
from datetime import datetime
from typing import Iterable, Mapping, Sequence

from libraries.analytics.perona import CostDriverDelta
from libraries.analytics.perona.ml_foundations import (
    FeatureStatistics,
    analyse_cost_relationships,
    compute_feature_statistics,
    recommend_best_practices,
)
from libraries.automation.render import optimization as render_optimization

from .datasets import (
    build_cost_training_dataset,
    build_default_lifecycle,
    build_default_render_log,
    build_default_telemetry,
    group_frame_times,
    load_persisted_render_metrics,
)
from .models import (
    CostBreakdown,
    CostModelInput,
    OptimizationResult,
    OptimizationScenario,
    PnLBreakdown,
    PnLContribution,
    RenderMetric,
    RiskIndicator,
    ShotLifecycle,
    ShotTelemetry,
    SUPPORTED_CURRENCIES,
    get_currency_symbol,
)
from .optimization import build_optimization_note
from .settings import (
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_PNL_BASELINE_COST,
    DEFAULT_TARGET_ERROR_RATE,
    SettingsLoadResult,
    _coerce_cost_model_input,
    _load_settings,
    _safe_float,
)

LOGGER = logging.getLogger(__name__)

_RISK_REFERENCE_TIME = datetime(2024, 5, 20, 12, 0)
_VARIANCE_CV_MAX = 0.02
_DEADLINE_HORIZON_HOURS = 7 * 24
_VARIANCE_WEIGHT = 0.2
_ERROR_WEIGHT = 0.4
_DEADLINE_WEIGHT = 0.4


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
        self._telemetry = build_default_telemetry()
        self._render_log = build_default_render_log(self._telemetry)
        self._frame_times_by_shot = group_frame_times(self._render_log)
        self._lifecycle = build_default_lifecycle()
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
        warning_messages = list(warnings)

        baseline_settings_raw = raw_settings.get("baseline_cost_input")
        if isinstance(baseline_settings_raw, Mapping):
            baseline_settings: Mapping[str, object] = baseline_settings_raw
        else:
            baseline_settings = dict[str, object]()
            if baseline_settings_raw is not None:
                message = (
                    "Ignoring invalid baseline_cost_input override "
                    f"{baseline_settings_raw!r}; using defaults"
                )
                LOGGER.warning(message)
                warning_messages.append(message)

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
            engine=engine,
            settings_path=resolved_path,
            warnings=tuple(warning_messages),
        )

    def latest_render_metric(self) -> RenderMetric | None:
        """Return the most recent render metric when available."""

        if not self._render_log:
            return None
        return self._render_log[-1]

    def stream_render_metrics(
        self,
        limit: int | None = None,
        *,
        sequence: str | None = None,
        shot_id: str | None = None,
        since: datetime | None = None,
    ) -> Iterable[RenderMetric]:
        """Return recent render metrics filtered by the supplied identifiers."""

        if limit is not None and limit <= 0:
            return

        filtered: list[RenderMetric] = [
            sample
            for sample in self._render_log
            if (sequence is None or sample.sequence == sequence)
            and (shot_id is None or sample.shot_id == shot_id)
            and (since is None or sample.timestamp >= since)
        ]
        if limit is not None:
            filtered = filtered[-limit:]
        for sample in filtered:
            yield sample

    def estimate_cost(self, inputs: CostModelInput) -> CostBreakdown:
        """Estimate the render costs for the supplied model inputs."""

        breakdown = render_optimization.estimate_cost(inputs.to_library())
        return CostBreakdown.from_library(breakdown, currency=inputs.currency)

    def risk_heatmap(self) -> Sequence[RiskIndicator]:
        """Return risk scores ordered from most to least critical."""

        indicators: list[RiskIndicator] = []
        target_error_rate = max(self._target_error_rate, 1e-6)
        weight_total = _VARIANCE_WEIGHT + _ERROR_WEIGHT + _DEADLINE_WEIGHT
        for telemetry in self._telemetry:
            frame_times = self._frame_times_by_shot.get(
                (telemetry.sequence, telemetry.shot_id),
                (),
            )
            if len(frame_times) > 1:
                variance = statistics.pvariance(frame_times)
                mean_frame_time = statistics.fmean(frame_times)
            elif frame_times:
                variance = 0.0
                mean_frame_time = frame_times[0]
            else:
                variance = 0.0
                mean_frame_time = telemetry.average_frame_time_ms

            if mean_frame_time <= 0:
                variance_score = 0.0
            else:
                std_dev = math.sqrt(variance)
                coefficient_variation = std_dev / mean_frame_time if std_dev else 0.0
                if coefficient_variation <= 0:
                    variance_score = 0.0
                else:
                    variance_score = min(1.0, coefficient_variation / _VARIANCE_CV_MAX)

            error_excess = max(0.0, telemetry.error_rate - target_error_rate)
            error_score = min(1.0, error_excess / target_error_rate)

            hours_remaining = (
                telemetry.deadline - _RISK_REFERENCE_TIME
            ).total_seconds() / 3600
            if hours_remaining <= 0:
                deadline_score = 1.0
            else:
                horizon = _DEADLINE_HORIZON_HOURS
                clamped_hours = min(hours_remaining, horizon)
                deadline_score = max(0.0, 1.0 - clamped_hours / horizon)

            weighted_sum = (
                variance_score * _VARIANCE_WEIGHT
                + error_score * _ERROR_WEIGHT
                + deadline_score * _DEADLINE_WEIGHT
            )
            normalised_score = weighted_sum / weight_total if weight_total else 0.0
            score = round(normalised_score * 100, 2)

            drivers: list[str] = []
            if variance_score >= 0.5:
                drivers.append("Render time volatility")
            if error_excess > 0:
                delta_pct = (telemetry.error_rate / target_error_rate - 1) * 100
                drivers.append(f"Error rate high (+{delta_pct:.1f}% vs target)")
            if hours_remaining <= 0:
                drivers.append("Deadline missed")
            elif deadline_score >= 0.25:
                drivers.append(f"Deadline pressure ({hours_remaining:.0f}h remaining)")
            if telemetry.cache_stability < 0.75:
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

    def cost_insights(
        self, top_n: int = 3
    ) -> tuple[tuple[FeatureStatistics, ...], tuple[str, ...]]:
        """Return feature statistics and actionable recommendations."""

        persisted_metrics = load_persisted_render_metrics(self._render_log)
        dataset = build_cost_training_dataset(
            self._telemetry,
            self._render_log,
            self._baseline_cost_input,
            self.estimate_cost,
            persisted_metrics=persisted_metrics,
        )
        statistics = compute_feature_statistics(dataset)
        importances = analyse_cost_relationships(dataset)
        recommendations = recommend_best_practices(importances, top_n=top_n)
        return statistics, recommendations

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
        library_baseline_input = baseline_input.to_library()
        library_scenarios = tuple(item.to_library() for item in scenarios)
        library_baseline_breakdown, projections = (
            render_optimization.simulate_optimizations(
                library_baseline_input, library_scenarios
            )
        )
        baseline_breakdown = CostBreakdown.from_library(
            library_baseline_breakdown, currency=baseline_input.currency
        )
        results: list[OptimizationResult] = []
        for scenario, projection in zip(scenarios, projections):
            breakdown = CostBreakdown.from_library(
                projection.breakdown, currency=baseline_input.currency
            )
            notes = scenario.notes or build_optimization_note(
                scenario, breakdown, baseline_breakdown, baseline_input
            )
            results.append(
                OptimizationResult(
                    name=projection.name,
                    total_cost=breakdown.total_cost,
                    cost_per_frame=breakdown.cost_per_frame,
                    gpu_hours=breakdown.gpu_hours,
                    render_hours=breakdown.render_hours,
                    savings_vs_baseline=projection.savings,
                    savings_percent=projection.savings_percent,
                    notes=notes,
                )
            )
        return baseline_breakdown, tuple(results)

    def shot_lifecycle(self) -> Sequence[ShotLifecycle]:
        """Return lifecycle timelines for monitored shots."""

        return self._lifecycle

    def _build_pnl_contributions(self) -> tuple[PnLContribution, ...]:
        baseline_cost = self._pnl_baseline_cost
        deltas = (
            CostDriverDelta(
                name="Resolution scale",
                metric_change_pct=10.0,
                cost_delta=round(baseline_cost * 0.15, 2),
                metric_label="resolution",
            ),
            CostDriverDelta(
                name="Sampling iterations",
                metric_change_pct=8.0,
                cost_delta=round(baseline_cost * 0.12, 2),
                metric_label="sampling iterations",
            ),
            CostDriverDelta(
                name="Shot revisions",
                metric_change_pct=5.0,
                cost_delta=round(baseline_cost * 0.05, 2),
                metric_label="shot revisions",
            ),
            CostDriverDelta(
                name="GPU spot pricing",
                metric_change_pct=-7.0,
                cost_delta=round(-baseline_cost * 0.08, 2),
                metric_label="spot pricing",
            ),
            CostDriverDelta(
                name="Queue efficiency",
                metric_change_pct=-6.0,
                cost_delta=round(-baseline_cost * 0.04, 2),
                metric_label="queue idle time",
            ),
        )
        contributions: list[PnLContribution] = []
        for delta in deltas:
            contributions.append(
                PnLContribution(
                    factor=delta.name,
                    delta_cost=round(delta.cost_delta, 2),
                    percentage_points=round(delta.cost_change_pct(baseline_cost), 1),
                    narrative=delta.describe(baseline_cost, precision=1),
                )
            )
        return tuple(contributions)


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
    "ShotTelemetry",
    "SUPPORTED_CURRENCIES",
    "get_currency_symbol",
]
