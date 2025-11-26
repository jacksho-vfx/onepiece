"""Reporting helpers powering dashboard exports."""

from __future__ import annotations

import csv
from datetime import datetime
from io import BytesIO, StringIO
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from libraries.analytics.perona.engine.engine import PeronaEngine
from libraries.analytics.perona.engine.models import get_currency_symbol

from .routes.analytics import compute_costs_summary, compute_risk_summary
from .routes.metrics import compute_metrics_summary
from .routes.shots import compute_shots_summary, filter_lifecycles


def _format_datetime(value: Any) -> str | None:
    """Return an ISO 8601 string for ``value`` when it represents a datetime."""

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _format_currency(
    amount: float | None, currency: str | None, *, precision: int = 2
) -> str:
    """Render ``amount`` using the symbol for ``currency`` when available."""

    if amount is None or currency is None:
        return "N/A"
    symbol = get_currency_symbol(currency)
    formatted = f"{abs(amount):,.{precision}f}"
    sign = "-" if amount < 0 else ""
    if symbol == currency:
        return f"{sign}{currency} {formatted}"
    return f"{sign}{symbol}{formatted}"


def build_daily_summary(
    engine: PeronaEngine,
    *,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the structured data used by the daily export."""

    generated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    metrics = compute_metrics_summary(engine, start_time=start_time, end_time=end_time)
    lifecycles = filter_lifecycles(
        engine.shot_lifecycle(), None, None, start_time, end_time
    )
    shots = compute_shots_summary(lifecycles)
    risk = compute_risk_summary(engine)
    costs = compute_costs_summary(engine, start_time=start_time, end_time=end_time)

    averages = metrics.get("averages", {})
    latest_sample = metrics.get("latest_sample") or {}
    metrics_section: dict[str, Any] = {
        "total_samples": metrics.get("total_samples", 0),
        "average_fps": averages.get("fps", 0.0),
        "average_frame_time_ms": averages.get("frame_time_ms", 0.0),
        "average_gpu_utilisation": averages.get("gpu_utilisation", 0.0),
        "average_error_count": averages.get("error_count", 0.0),
        "timeline": metrics.get("timeline", []),
    }
    if latest_sample:
        metrics_section["latest_sample"] = {
            "sequence": latest_sample.get("sequence"),
            "shot_id": latest_sample.get("shot_id"),
            "timestamp": latest_sample.get("timestamp"),
        }

    active_shots: list[dict[str, Any]] = []
    for item in shots.get("active_shots", [])[:5]:
        stage_metrics = item.get("stage_metrics") or {}
        stage_metrics_summary = ", ".join(
            f"{key}={value}" for key, value in sorted(stage_metrics.items())
        )
        active_shots.append(
            {
                "sequence": item.get("sequence"),
                "shot_id": item.get("shot_id"),
                "current_stage": item.get("current_stage"),
                "stage_started_at": _format_datetime(item.get("stage_started_at")),
                "stage_metrics": stage_metrics_summary,
            }
        )

    shots_section = {
        "total": shots.get("total", 0),
        "completed": shots.get("completed", 0),
        "active": shots.get("active", 0),
        "by_stage": shots.get("by_stage", [])[:3],
        "by_sequence": shots.get("by_sequence", [])[:3],
        "notable_active": active_shots,
    }

    top_risks = []
    for item in risk.get("top_risks", [])[:3]:
        drivers = item.get("drivers") or []
        if isinstance(drivers, list):
            drivers = ", ".join(drivers)
        top_risks.append(
            {
                "sequence": item.get("sequence"),
                "shot_id": item.get("shot_id"),
                "risk_score": item.get("risk_score"),
                "drivers": drivers,
            }
        )

    risk_section = {
        "count": risk.get("count", 0),
        "average_risk": risk.get("average_risk", 0.0),
        "max_risk": risk.get("max_risk"),
        "min_risk": risk.get("min_risk"),
        "critical_count": len(risk.get("critical", [])),
        "top_risks": top_risks,
    }

    pnl = costs.get("pnl", {})
    cost_per_frame = costs.get("cost_per_frame", {})
    top_contributors = [
        {
            "factor": contribution.get("factor"),
            "delta_cost": contribution.get("delta_cost"),
        }
        for contribution in pnl.get("contributions", [])[:3]
    ]

    costs_section = {
        "currency": costs.get("currency"),
        "baseline_total_cost": costs.get("baseline", {}).get("total_cost"),
        "current_total_cost": pnl.get("current_cost"),
        "delta_total_cost": pnl.get("delta_cost"),
        "baseline_cost_per_frame": cost_per_frame.get("baseline"),
        "current_cost_per_frame": cost_per_frame.get("current"),
        "delta_cost_per_frame": cost_per_frame.get("delta"),
        "top_contributors": top_contributors,
    }

    return {
        "generated_at": generated_at,
        "window": metrics.get("window")
        or {"from": start_time.isoformat() if start_time else None, "to": None},
        "metrics": metrics_section,
        "shots": shots_section,
        "risk": risk_section,
        "costs": costs_section,
    }


def _flatten_summary_rows(
    payload: Mapping[str, Any], prefix: str = ""
) -> list[tuple[str, str]]:
    """Return flattened key/value rows for CSV rendering."""

    rows: list[tuple[str, str]] = []
    for key, value in payload.items():
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, Mapping):
            rows.extend(_flatten_summary_rows(value, full_key))
            continue
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            if not value:
                rows.append((full_key, ""))
                continue
            for index, item in enumerate(value, start=1):
                item_key = f"{full_key}[{index}]"
                if isinstance(item, Mapping):
                    rows.extend(_flatten_summary_rows(item, item_key))
                else:
                    rows.append((item_key, "" if item is None else str(item)))
            continue
        rows.append((full_key, "" if value is None else str(value)))
    return rows


def render_daily_csv(summary: Mapping[str, Any]) -> bytes:
    """Return the CSV payload for the supplied ``summary`` data."""

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["metric", "value"])
    for key, value in _flatten_summary_rows(summary):
        writer.writerow([key, value])
    return buffer.getvalue().encode("utf-8")


def _summary_lines(summary: Mapping[str, Any]) -> list[str]:
    """Generate human-readable lines describing the daily summary."""

    metrics = summary.get("metrics", {})
    shots = summary.get("shots", {})
    risk = summary.get("risk", {})
    costs = summary.get("costs", {})

    currency = costs.get("currency")
    lines = [
        "Perona Daily Summary",
        f"Generated: {summary.get('generated_at', '')}",
        "",
        "Render Metrics",
        f"  Samples analysed: {metrics.get('total_samples', 0)}",
        (
            "  Averages: "
            f"fps={metrics.get('average_fps', 0.0)}, "
            f"frame_time_ms={metrics.get('average_frame_time_ms', 0.0)}, "
            f"gpu_utilisation={metrics.get('average_gpu_utilisation', 0.0)}, "
            f"error_count={metrics.get('average_error_count', 0.0)}"
        ),
    ]

    latest = metrics.get("latest_sample")
    if isinstance(latest, Mapping):
        lines.append(
            "  Latest sample: "
            f"{latest.get('sequence', 'N/A')} {latest.get('shot_id', '')} at "
            f"{latest.get('timestamp', 'N/A')}"
        )

    lines.append("")
    lines.append(
        "Shots summary: "
        f"total={shots.get('total', 0)}, completed={shots.get('completed', 0)}, "
        f"active={shots.get('active', 0)}"
    )

    lines.append("  By stage:")
    by_stage = shots.get("by_stage", [])
    if by_stage:
        for entry in by_stage:
            lines.append(f"    - {entry.get('name')}: {entry.get('shots')}")
    else:
        lines.append("    - No stages tracked")

    lines.append("  By sequence:")
    by_sequence = shots.get("by_sequence", [])
    if by_sequence:
        for entry in by_sequence:
            lines.append(f"    - {entry.get('name')}: {entry.get('shots')}")
    else:
        lines.append("    - No sequences tracked")

    notable = shots.get("notable_active", [])
    if notable:
        lines.append("  Active focus shots:")
        for shot in notable:
            parts = [
                f"{shot.get('sequence', 'N/A')} {shot.get('shot_id', '')}",
                f"stage={shot.get('current_stage', 'unknown')}",
            ]
            if shot.get("stage_started_at"):
                parts.append(f"since {shot['stage_started_at']}")
            if shot.get("stage_metrics"):
                parts.append(shot["stage_metrics"])
            lines.append("    - " + " — ".join(parts))
    else:
        lines.append("  Active focus shots: None")

    lines.append("")
    lines.append("Risk summary:")
    lines.append(
        "  Counts: "
        f"total={risk.get('count', 0)}, critical={risk.get('critical_count', 0)}"
    )
    top_risks = risk.get("top_risks", [])
    if top_risks:
        lines.append("  Top risks:")
        for item in top_risks:
            lines.append(
                "    - "
                + f"{item.get('sequence', 'N/A')} {item.get('shot_id', '')}: "
                + f"score={item.get('risk_score', 0)}"
                + (f" drivers={item.get('drivers')}" if item.get("drivers") else "")
            )
    else:
        lines.append("  Top risks: None")

    lines.append("")
    lines.append("Cost summary:")
    lines.append(
        "  Total cost baseline/current/delta: "
        + "/".join(
            [
                _format_currency(costs.get("baseline_total_cost"), currency),
                _format_currency(costs.get("current_total_cost"), currency),
                _format_currency(costs.get("delta_total_cost"), currency),
            ]
        )
    )
    lines.append(
        "  Cost per frame (baseline/current/delta): "
        + "/".join(
            [
                _format_currency(
                    costs.get("baseline_cost_per_frame"), currency, precision=4
                ),
                _format_currency(
                    costs.get("current_cost_per_frame"), currency, precision=4
                ),
                _format_currency(
                    costs.get("delta_cost_per_frame"), currency, precision=4
                ),
            ]
        )
    )

    contributors = costs.get("top_contributors", [])
    if contributors:
        lines.append("  Key contributors:")
        for item in contributors:
            lines.append(
                "    - "
                + f"{item.get('factor', 'Unknown')}: "
                + _format_currency(item.get("delta_cost"), currency)
            )
    else:
        lines.append("  Key contributors: None")

    return lines


def render_daily_pdf(summary: Mapping[str, Any]) -> bytes:
    """Render ``summary`` into a simple PDF document."""

    lines = _summary_lines(summary)
    font = ImageFont.load_default()

    dummy = Image.new("RGB", (1, 1), color="white")
    draw = ImageDraw.Draw(dummy)
    text_heights: list[int] = []
    text_widths: list[int] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        width = int(bbox[2] - bbox[0])
        height = int(bbox[3] - bbox[1])
        text_heights.append(height)
        text_widths.append(width)

    padding_x: int = 24
    padding_y: int = 24
    line_spacing: int = 4
    width = int(max(text_widths or [0]) + padding_x * 2)
    height = int(
        sum(text_heights or [0]) + padding_y * 2 + line_spacing * max(len(lines) - 1, 0)
    )

    image_width = int(max(width, 200))
    image_height = int(max(height, 200))
    image = Image.new("RGB", (image_width, image_height), color="white")
    draw = ImageDraw.Draw(image)
    y: int = padding_y
    for idx, line in enumerate(lines):
        draw.text((padding_x, y), line, fill="black", font=font)
        y += int(text_heights[idx] + line_spacing)

    buffer = BytesIO()
    image.save(buffer, format="PDF")
    return buffer.getvalue()


__all__ = [
    "build_daily_summary",
    "render_daily_csv",
    "render_daily_pdf",
]
