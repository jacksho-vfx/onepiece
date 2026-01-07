"""Render farm reporting helpers for Deadline utilisation summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import typer


@dataclass(frozen=True)
class DeadlineMetric:
    timestamp: datetime
    pool: str
    utilisation: float
    optimisation: float


@dataclass(frozen=True)
class WeeklyAggregate:
    week_start: date
    week_end: date
    pool: str
    utilisation_avg: float
    optimisation_avg: float
    sample_count: int


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:  # pragma: no cover - guard for invalid data
        raise typer.BadParameter(f"Invalid timestamp '{value}'.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed


def _parse_ratio(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise typer.BadParameter(f"{label} must be numeric.")
    numeric = float(value)
    if numeric < 0:
        raise typer.BadParameter(f"{label} must be non-negative.")
    if numeric <= 1:
        return numeric
    if numeric <= 100:
        return numeric / 100
    raise typer.BadParameter(f"{label} must be between 0 and 1 (or 0 and 100).")


def _parse_metric(raw: Mapping[str, Any]) -> DeadlineMetric:
    timestamp_raw = raw.get("timestamp") or raw.get("date")
    if not isinstance(timestamp_raw, str):
        raise typer.BadParameter("Each metric requires a 'timestamp' string.")
    pool = raw.get("pool")
    if not isinstance(pool, str) or not pool.strip():
        raise typer.BadParameter("Each metric requires a non-empty 'pool' value.")
    utilisation = _parse_ratio(raw.get("utilisation"), "utilisation")
    optimisation = raw.get("optimisation")
    if optimisation is None:
        optimisation = raw.get("optimization")
    if optimisation is None:
        optimisation = raw.get("optimization_savings")
    if optimisation is None:
        raise typer.BadParameter(
            "Each metric requires an 'optimisation' (or 'optimization') value."
        )
    optimisation_ratio = _parse_ratio(optimisation, "optimisation")
    return DeadlineMetric(
        timestamp=_parse_timestamp(timestamp_raw),
        pool=pool.strip(),
        utilisation=utilisation,
        optimisation=optimisation_ratio,
    )


def _load_metrics(path: Path) -> list[DeadlineMetric]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(f"Unable to read '{path}': {exc}.") from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON in '{path}': {exc}.") from exc

    if isinstance(payload, dict):
        payload = payload.get("metrics")
    if not isinstance(payload, list):
        raise typer.BadParameter("Metrics payload must be a list of entries.")

    metrics: list[DeadlineMetric] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise typer.BadParameter("Each metric entry must be an object.")
        metrics.append(_parse_metric(entry))
    return metrics


def _iter_week_ranges(deadline: date, weeks: int) -> list[tuple[date, date]]:
    ranges = []
    for offset in range(weeks):
        week_end = deadline - timedelta(days=7 * offset)
        week_start = week_end - timedelta(days=6)
        ranges.append((week_start, week_end))
    ranges.reverse()
    return ranges


def _aggregate_weekly(
    metrics: Iterable[DeadlineMetric], week_ranges: list[tuple[date, date]]
) -> list[WeeklyAggregate]:
    buckets: dict[tuple[date, date, str], list[DeadlineMetric]] = {}
    for metric in metrics:
        metric_date = metric.timestamp.date()
        for week_start, week_end in week_ranges:
            if week_start <= metric_date <= week_end:
                key = (week_start, week_end, metric.pool)
                buckets.setdefault(key, []).append(metric)
                break

    aggregates: list[WeeklyAggregate] = []
    for (week_start, week_end, pool), entries in sorted(buckets.items()):
        utilisation_avg = sum(item.utilisation for item in entries) / len(entries)
        optimisation_avg = sum(item.optimisation for item in entries) / len(entries)
        aggregates.append(
            WeeklyAggregate(
                week_start=week_start,
                week_end=week_end,
                pool=pool,
                utilisation_avg=utilisation_avg,
                optimisation_avg=optimisation_avg,
                sample_count=len(entries),
            )
        )
    return aggregates


def _format_percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_bar(value: float, width: int = 24) -> str:
    clamped = max(0.0, min(1.0, value))
    filled = round(clamped * width)
    return f"{'█' * filled}{'·' * (width - filled)}"


def _render_markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def _format_row(values: list[str]) -> str:
        padded = [value.ljust(widths[index]) for index, value in enumerate(values)]
        return f"| {' | '.join(padded)} |"

    lines = [_format_row(headers)]
    lines.append(
        f"| {' | '.join('-' * width for width in widths)} |"
    )
    lines.extend(_format_row(row) for row in rows)
    return lines


def _render_report(
    *,
    deadline: date,
    pools: list[str] | None,
    week_ranges: list[tuple[date, date]],
    aggregates: list[WeeklyAggregate],
    metrics_count: int,
) -> str:
    pool_label = ", ".join(pools) if pools else "all"
    lines: list[str] = [
        "# Render Farm Weekly Report",
        "",
        f"Deadline: {deadline.isoformat()}",
        f"Pools: {pool_label}",
        "",
        "## Summary",
        f"- Total metrics: {metrics_count}",
        f"- Weeks covered: {len(week_ranges)}",
    ]

    if aggregates:
        overall_utilisation = sum(a.utilisation_avg for a in aggregates) / len(
            aggregates
        )
        overall_optimisation = sum(a.optimisation_avg for a in aggregates) / len(
            aggregates
        )
        lines.extend(
            [
                f"- Average utilisation: {_format_percentage(overall_utilisation)}",
                f"- Average optimisation: {_format_percentage(overall_optimisation)}",
            ]
        )
    else:
        lines.append("- No metrics found for the requested window.")

    lines.append("")
    lines.append("## Weekly Overview")

    weekly_rows: list[list[str]] = []
    for week_start, week_end in week_ranges:
        week_entries = [
            aggregate
            for aggregate in aggregates
            if aggregate.week_start == week_start and aggregate.week_end == week_end
        ]
        if week_entries:
            utilisation_avg = sum(a.utilisation_avg for a in week_entries) / len(
                week_entries
            )
            optimisation_avg = sum(a.optimisation_avg for a in week_entries) / len(
                week_entries
            )
            sample_count = sum(a.sample_count for a in week_entries)
        else:
            utilisation_avg = 0.0
            optimisation_avg = 0.0
            sample_count = 0
        weekly_rows.append(
            [
                f"{week_start.isoformat()} → {week_end.isoformat()}",
                _format_percentage(utilisation_avg),
                _format_percentage(optimisation_avg),
                str(sample_count),
            ]
        )

    lines.extend(
        _render_markdown_table(
            ["Week", "Utilisation", "Optimisation", "Samples"], weekly_rows
        )
    )
    lines.append("")
    lines.append("## Weekly Pool Breakdown")

    if not aggregates:
        lines.append("No pool data available for the requested window.")
    else:
        for week_start, week_end in week_ranges:
            week_entries = [
                aggregate
                for aggregate in aggregates
                if aggregate.week_start == week_start and aggregate.week_end == week_end
            ]
            if not week_entries:
                continue
            lines.append(f"### {week_start.isoformat()} → {week_end.isoformat()}")
            pool_rows = [
                [
                    aggregate.pool,
                    _format_percentage(aggregate.utilisation_avg),
                    _format_percentage(aggregate.optimisation_avg),
                    str(aggregate.sample_count),
                ]
                for aggregate in week_entries
            ]
            lines.extend(
                _render_markdown_table(
                    ["Pool", "Utilisation", "Optimisation", "Samples"], pool_rows
                )
            )
            lines.append("")

    lines.append("## Visualisations")
    lines.append("")
    lines.append("### Utilisation (weekly average)")
    for row in weekly_rows:
        bar = _format_bar(float(row[1].rstrip("%")) / 100)
        lines.append(f"- {row[0]} | {bar} {row[1]}")
    lines.append("")
    lines.append("### Optimisation (weekly average)")
    for row in weekly_rows:
        bar = _format_bar(float(row[2].rstrip("%")) / 100)
        lines.append(f"- {row[0]} | {bar} {row[2]}")

    return "\n".join(lines).rstrip() + "\n"


def _parse_deadline(value: str | None) -> date:
    if value is None:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("Deadline must be in YYYY-MM-DD format.") from exc


def generate_weekly_report(
    input_path: Path = typer.Option(
        ..., "--input", exists=True, dir_okay=False, readable=True
    ),
    deadline: str | None = typer.Option(
        None, "--deadline", help="Deadline date in YYYY-MM-DD (defaults to today)."
    ),
    weeks: int = typer.Option(
        4,
        "--weeks",
        min=1,
        max=52,
        help="Number of weeks to include counting back from the deadline.",
    ),
    pool: list[str] | None = typer.Option(
        None,
        "--pool",
        help="Only include metrics from the specified Deadline pool (repeatable).",
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Optional path to write the report markdown."
    ),
) -> None:
    """Generate a weekly utilisation and optimisation report from Deadline metrics."""

    deadline_date = _parse_deadline(deadline)
    metrics = _load_metrics(input_path)

    pools = [entry.strip() for entry in pool or [] if entry.strip()]
    if pools:
        metrics = [metric for metric in metrics if metric.pool in pools]

    week_ranges = _iter_week_ranges(deadline_date, weeks)
    aggregates = _aggregate_weekly(metrics, week_ranges)
    report = _render_report(
        deadline=deadline_date,
        pools=pools or None,
        week_ranges=week_ranges,
        aggregates=aggregates,
        metrics_count=len(metrics),
    )

    if output is None:
        typer.echo(report)
        return
    output.write_text(report, encoding="utf-8")
    typer.echo(f"Report written to {output}")


__all__ = ["generate_weekly_report"]
