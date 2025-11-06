"""Formatting helpers for the Perona CLI commands."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Mapping, NotRequired, Sequence, TypedDict

from libraries.analytics.perona.engine import (
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_PNL_BASELINE_COST,
    DEFAULT_TARGET_ERROR_RATE,
    get_currency_symbol,
)
from libraries.analytics.perona.ml_foundations import FeatureStatistics
from libraries.analytics.perona.models import (
    CostEstimate,
    RiskIndicator as RiskIndicatorModel,
)


class DifferenceEntry(TypedDict):
    """Structure describing a difference between current and default values."""

    current: object
    default: object | None
    delta: NotRequired[float | int]


class SettingsDifferences(TypedDict, total=False):
    """Structured collection of settings differences."""

    baseline_cost_input: dict[str, DifferenceEntry]
    target_error_rate: DifferenceEntry
    pnl_baseline_cost: DifferenceEntry


def _format_value(value: object) -> str:
    """Render numeric values with thousands separators where possible."""

    if isinstance(value, float):
        return f"{value:,}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _format_currency_amount(amount: float, currency: str) -> str:
    """Return ``amount`` prefixed with the symbol for ``currency`` when known."""

    symbol = get_currency_symbol(currency)
    formatted = _format_value(abs(amount))
    sign = "-" if amount < 0 else ""
    if symbol == currency:
        return f"{sign}{currency} {formatted}"
    return f"{sign}{symbol}{formatted}"


def _humanise_key(key: str) -> str:
    """Convert snake_case keys into a more readable variant."""

    overrides = {"gpu": "GPU", "gb": "GB", "ms": "ms", "pnl": "P&L"}
    words = key.split("_")
    return " ".join(overrides.get(word, word.capitalize()) for word in words)


def _format_difference_line(
    label: str,
    entry: DifferenceEntry,
    *,
    width: int,
    indent: str = "",
) -> str:
    """Render a single line describing a deviation from defaults."""

    current = entry["current"]
    default = entry["default"]
    delta = entry.get("delta")
    detail_parts: list[str] = []
    if delta is not None:
        delta_display = _format_value(delta)
        if isinstance(delta, (int, float)) and delta > 0:
            delta_display = f"+{delta_display}"
        detail_parts.append(f"Δ {delta_display}")
    if default is not None:
        detail_parts.append(f"default {_format_value(default)}")
    detail = ", ".join(detail_parts)
    suffix = f" ({detail})" if detail else ""
    return f"{indent}{label:<{width}} : {_format_value(current)}{suffix}"


def _diff_numeric(current: object, default: object) -> float | int | None:
    """Return the numeric delta between two values when applicable."""

    numeric_types = (int, float)
    if isinstance(current, numeric_types) and isinstance(default, numeric_types):
        return current - default
    return None


def _diff_mapping(
    current: Mapping[str, object], default: Mapping[str, object]
) -> dict[str, DifferenceEntry]:
    """Identify key/value differences between two mappings."""

    differences: dict[str, DifferenceEntry] = {}
    for key, value in current.items():
        default_value = default.get(key)
        if value != default_value:
            entry: DifferenceEntry = {"current": value, "default": default_value}
            delta = _diff_numeric(value, default_value)
            if delta is not None:
                entry["delta"] = delta
            differences[key] = entry
    return differences


def _calculate_settings_differences(
    baseline: Mapping[str, object],
    target_error_rate: float,
    pnl_baseline_cost: float,
) -> SettingsDifferences:
    """Return a structured diff against the baked-in Perona defaults."""

    baseline_defaults = asdict(DEFAULT_BASELINE_COST_INPUT)
    baseline_diffs = _diff_mapping(baseline, baseline_defaults)
    differences: SettingsDifferences = {}
    if baseline_diffs:
        differences["baseline_cost_input"] = baseline_diffs

    def _diff_scalar(current: object, default: object) -> DifferenceEntry | None:
        if current == default:
            return None
        entry: DifferenceEntry = {"current": current, "default": default}
        delta = _diff_numeric(current, default)
        if delta is not None:
            entry["delta"] = delta
        return entry

    target_diff = _diff_scalar(target_error_rate, DEFAULT_TARGET_ERROR_RATE)
    if target_diff is not None:
        differences["target_error_rate"] = target_diff

    pnl_diff = _diff_scalar(pnl_baseline_cost, DEFAULT_PNL_BASELINE_COST)
    if pnl_diff is not None:
        differences["pnl_baseline_cost"] = pnl_diff

    return differences


def _format_settings_table(
    baseline: Mapping[str, object],
    target_error_rate: float,
    pnl_baseline_cost: float,
    *,
    settings_path: Path | None,
    differences: SettingsDifferences | None = None,
) -> str:
    """Produce a readable summary of the resolved Perona settings."""

    humanised_keys = {key: _humanise_key(key) for key in baseline}
    width = max(
        [len(name) for name in humanised_keys.values()]
        + [len("Target error rate"), len("P&L baseline cost")]
    )
    lines: list[str] = []
    if settings_path is not None:
        lines.append(f"Settings file: {settings_path}")
        lines.append("")
    lines.append("Baseline cost inputs")
    lines.append("-" * len("Baseline cost inputs"))
    for key, value in baseline.items():
        display_key = humanised_keys[key]
        lines.append(f"{display_key:<{width}} : {_format_value(value)}")
    lines.append("")
    lines.append(f"{'Target error rate':<{width}} : {_format_value(target_error_rate)}")
    lines.append(f"{'P&L baseline cost':<{width}} : {_format_value(pnl_baseline_cost)}")

    if differences is not None:
        lines.append("")
        header = "Differences from defaults"
        lines.append(header)
        lines.append("-" * len(header))
        if not differences:
            lines.append("No differences detected (using default settings).")
        else:
            baseline_diffs = differences.get("baseline_cost_input")
            if baseline_diffs:
                lines.append("Baseline cost inputs")
                for key in baseline:
                    entry = baseline_diffs.get(key)
                    if entry is None:
                        continue
                    display_key = humanised_keys.get(key, _humanise_key(key))
                    lines.append(
                        _format_difference_line(
                            display_key,
                            entry,
                            width=width,
                            indent="  ",
                        )
                    )
            target_diff = differences.get("target_error_rate")
            if target_diff is not None:
                lines.append(
                    _format_difference_line(
                        "Target error rate",
                        target_diff,
                        width=width,
                    )
                )
            pnl_diff = differences.get("pnl_baseline_cost")
            if pnl_diff is not None:
                lines.append(
                    _format_difference_line(
                        "P&L baseline cost",
                        pnl_diff,
                        width=width,
                    )
                )
    return "\n".join(lines)


def _format_cost_breakdown_table(estimate: CostEstimate) -> str:
    """Render a tabular summary of the cost estimate."""

    labels = {
        "frame_count": "Frame count",
        "gpu_hours": "GPU hours",
        "render_hours": "Render hours",
        "concurrency": "Concurrency",
        "gpu_cost": "GPU cost",
        "render_farm_cost": "Render farm cost",
        "storage_cost": "Storage cost",
        "egress_cost": "Egress cost",
        "misc_cost": "Misc cost",
        "total_cost": "Total cost",
        "cost_per_frame": "Cost per frame",
        "currency": "Currency",
    }
    values = estimate.model_dump()
    width = max(len(label) for label in labels.values())
    currency_fields = {
        "gpu_cost",
        "render_farm_cost",
        "storage_cost",
        "egress_cost",
        "misc_cost",
        "total_cost",
        "cost_per_frame",
    }
    lines = ["Cost estimate", "-" * len("Cost estimate")]
    for key, label in labels.items():
        value = values[key]
        if key in currency_fields:
            display = _format_currency_amount(float(value), estimate.currency)
        else:
            display = _format_value(value)
        lines.append(f"{label:<{width}} : {display}")
    return "\n".join(lines)


def _format_cost_insights(
    statistics: tuple[FeatureStatistics, ...],
    recommendations: tuple[str, ...],
    *,
    settings_path: Path | None,
) -> str:
    """Render cost telemetry statistics and recommendations."""

    lines: list[str] = []
    if settings_path is not None:
        lines.append(f"Settings file: {settings_path}")
        lines.append("")

    header = "Cost telemetry insights"
    lines.append(header)
    lines.append("-" * len(header))

    if statistics:
        display_rows: list[tuple[str, FeatureStatistics]] = [
            (_humanise_key(entry.name), entry) for entry in statistics
        ]
        name_width = max(len("Feature"), *(len(name) for name, _ in display_rows))
        mean_values = [_format_value(entry.mean) for _, entry in display_rows]
        stddev_values = [_format_value(entry.stddev) for _, entry in display_rows]
        min_values = [_format_value(entry.minimum) for _, entry in display_rows]
        max_values = [_format_value(entry.maximum) for _, entry in display_rows]

        mean_width = max(len("Mean"), *(len(value) for value in mean_values))
        stddev_width = max(len("Std dev"), *(len(value) for value in stddev_values))
        min_width = max(len("Minimum"), *(len(value) for value in min_values))
        max_width = max(len("Maximum"), *(len(value) for value in max_values))

        header_line = (
            f"{'Feature':<{name_width}}  "
            f"{'Mean':>{mean_width}}  "
            f"{'Std dev':>{stddev_width}}  "
            f"{'Minimum':>{min_width}}  "
            f"{'Maximum':>{max_width}}"
        )
        lines.append(header_line)
        lines.append(
            f"{'-' * name_width}  "
            f"{'-' * mean_width}  "
            f"{'-' * stddev_width}  "
            f"{'-' * min_width}  "
            f"{'-' * max_width}"
        )

        for (name, entry), mean_value, stddev_value, min_value, max_value in zip(
            display_rows, mean_values, stddev_values, min_values, max_values
        ):
            lines.append(
                f"{name:<{name_width}}  "
                f"{mean_value:>{mean_width}}  "
                f"{stddev_value:>{stddev_width}}  "
                f"{min_value:>{min_width}}  "
                f"{max_value:>{max_width}}"
            )
    else:
        lines.append("No telemetry statistics available.")

    lines.append("")
    rec_header = "Recommendations"
    lines.append(rec_header)
    lines.append("-" * len(rec_header))
    if recommendations:
        lines.extend(f"- {message}" for message in recommendations)
    else:
        lines.append("No recommendations generated.")

    return "\n".join(lines)


def _format_risk_heatmap(
    indicators: Sequence[RiskIndicatorModel],
    *,
    settings_path: Path | None,
    total_count: int,
) -> str:
    """Render the risk heatmap highlighting the most critical shots."""

    lines: list[str] = []
    if settings_path is not None:
        lines.append(f"Settings file: {settings_path}")
        lines.append("")

    header = "Risk heatmap"
    lines.append(header)
    lines.append("-" * len(header))

    if not indicators:
        lines.append("No risk indicators available.")
        return "\n".join(lines)

    sequence_width = max(len("Sequence"), *(len(item.sequence) for item in indicators))
    shot_width = max(len("Shot"), *(len(item.shot_id) for item in indicators))
    risk_width = len("Risk score")
    render_width = len("Render ms")
    error_width = len("Error rate")
    cache_width = len("Cache stability")

    for item in indicators:
        risk_width = max(risk_width, len(_format_value(item.risk_score)))
        render_width = max(render_width, len(_format_value(item.render_time_ms)))
        error_width = max(error_width, len(_format_value(item.error_rate)))
        cache_width = max(cache_width, len(_format_value(item.cache_stability)))

    lines.append(
        f"{'Sequence':<{sequence_width}}  "
        f"{'Shot':<{shot_width}}  "
        f"{'Risk score':>{risk_width}}  "
        f"{'Render ms':>{render_width}}  "
        f"{'Error rate':>{error_width}}  "
        f"{'Cache stability':>{cache_width}}  Drivers"
    )
    lines.append(
        f"{'-' * sequence_width}  "
        f"{'-' * shot_width}  "
        f"{'-' * risk_width}  "
        f"{'-' * render_width}  "
        f"{'-' * error_width}  "
        f"{'-' * cache_width}  "
        "-------"
    )

    for indicator in indicators:
        drivers = ", ".join(indicator.drivers) if indicator.drivers else "-"
        lines.append(
            f"{indicator.sequence:<{sequence_width}}  "
            f"{indicator.shot_id:<{shot_width}}  "
            f"{_format_value(indicator.risk_score):>{risk_width}}  "
            f"{_format_value(indicator.render_time_ms):>{render_width}}  "
            f"{_format_value(indicator.error_rate):>{error_width}}  "
            f"{_format_value(indicator.cache_stability):>{cache_width}}  "
            f"{drivers}"
        )

    if len(indicators) < total_count:
        lines.append("")
        lines.append(f"Showing top {len(indicators)} of {total_count} indicators.")

    return "\n".join(lines)


__all__ = [
    "DifferenceEntry",
    "SettingsDifferences",
    "_calculate_settings_differences",
    "_format_cost_breakdown_table",
    "_format_cost_insights",
    "_format_risk_heatmap",
    "_format_settings_table",
]
