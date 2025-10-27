"""FastAPI surface exposing Perona dashboard analytics."""

from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import Counter
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from statistics import fmean
from threading import Lock
from typing import Any, Mapping, NamedTuple, Sequence

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict, Field

from apps.perona.version import PERONA_VERSION

from libraries.analytics.perona.engine import (
    DEFAULT_SETTINGS_PATH,
    PeronaEngine,
    ShotLifecycle,
    get_currency_symbol,
)
from libraries.analytics.perona.models import (
    CostEstimate,
    CostEstimateRequest,
    CostInsightResponse,
    OptimizationBacktestRequest,
    OptimizationBacktestResponse,
    OptimizationResult,
    PnLBreakdown,
    RenderMetric,
    RiskIndicator,
    Shot,
    SettingsSummary,
    sequences_from_lifecycles,
)
from libraries.analytics.perona.models import Sequence as PeronaSequence
from libraries.analytics.perona.ml_foundations import FeatureStatistics


class RenderMetricBatch(BaseModel):
    """Payload wrapper for render metrics ingested via the API."""

    metrics: tuple[RenderMetric, ...] = Field(default_factory=tuple)

    model_config = ConfigDict(populate_by_name=True)

    def to_serialisable(self) -> list[dict[str, Any]]:
        """Return JSON-friendly dictionaries for persistence."""

        return [
            metric.model_dump(mode="json", by_alias=True) for metric in self.metrics
        ]


class RenderMetricStore:
    """Simple append-only store that persists render metrics to disk."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    def persist(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Append metrics to the backing store as NDJSON."""

        if not records:
            return

        lines = [
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            for record in records
        ]
        payload = "\n".join(lines) + "\n"

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(payload)


def _resolve_metrics_store_path() -> Path:
    """Return the configured metrics store path, falling back to cache dir."""

    env_path = os.getenv("PERONA_METRICS_PATH")
    if env_path:
        return Path(env_path).expanduser()

    cache_home = os.getenv("XDG_CACHE_HOME")
    base_dir = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return base_dir / "perona" / "render-metrics.ndjson"


app = FastAPI(
    title="Perona",
    description=(
        "Real-time VFX performance & cost dashboard inspired by quant trading systems. "
        "The API surfaces telemetry, risk scoring, cost attribution and optimisation "
        "backtests that power the interactive UI."
    ),
    version=PERONA_VERSION,
)


_metrics_store = RenderMetricStore(_resolve_metrics_store_path())


def _dashboard_index_html() -> str:
    """Return the bundled HTML shell for the interactive dashboard."""

    template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Perona Dashboard</title>
    <style>
        :root {
            color-scheme: dark;
            font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: #0f172a;
            color: #f8fafc;
        }

        body {
            margin: 0;
            min-height: 100vh;
            background: radial-gradient(circle at top, rgba(56, 189, 248, 0.16), transparent 45%), #0f172a;
        }

        header {
            padding: 2.5rem 1.5rem 1.5rem;
            text-align: center;
        }

        header h1 {
            margin: 0;
            font-size: clamp(2rem, 4vw, 2.8rem);
            letter-spacing: 0.05em;
        }

        header p {
            color: #94a3b8;
            margin: 0.75rem auto 0;
            max-width: 640px;
        }

        main {
            padding: 1rem 1.5rem 3.5rem;
            max-width: 1120px;
            margin: 0 auto;
        }

        .grid {
            display: grid;
            gap: 1.25rem;
        }

        @media (min-width: 768px) {
            .grid {
                grid-template-columns: repeat(12, 1fr);
            }
        }

        .card {
            background: rgba(15, 23, 42, 0.78);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 18px;
            padding: 1.35rem 1.6rem;
            box-shadow: 0 22px 55px rgba(15, 23, 42, 0.42);
            backdrop-filter: blur(18px);
        }

        .card h2 {
            margin: 0;
            font-size: 1.05rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #38bdf8;
        }

        .card h3 {
            margin: 1.25rem 0 0.5rem;
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.1em;
            color: #94a3b8;
        }

        .span-12 { grid-column: span 12; }
        .span-8 { grid-column: span 12; }
        .span-6 { grid-column: span 12; }
        .span-4 { grid-column: span 12; }

        @media (min-width: 768px) {
            .span-8 { grid-column: span 8; }
            .span-6 { grid-column: span 6; }
            .span-4 { grid-column: span 4; }
        }

        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 0.9rem;
            margin-top: 1.35rem;
        }

        .stat {
            padding: 0.85rem;
            border-radius: 14px;
            background: rgba(30, 41, 59, 0.82);
            border: 1px solid rgba(148, 163, 184, 0.1);
        }

        .stat .label {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.7rem;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .info-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.1rem;
            height: 1.1rem;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.24);
            color: #e0f2fe;
            font-size: 0.65rem;
            font-weight: 600;
            cursor: help;
            position: relative;
            flex-shrink: 0;
        }

        .info-icon::before {
            content: "i";
        }

        .info-icon::after {
            content: attr(data-tooltip);
            position: absolute;
            bottom: calc(100% + 0.5rem);
            left: 50%;
            transform: translate(-50%, 4px);
            background: rgba(15, 23, 42, 0.92);
            color: #f8fafc;
            padding: 0.45rem 0.6rem;
            border-radius: 0.6rem;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.55);
            max-width: 240px;
            width: max-content;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.15s ease, transform 0.15s ease;
            font-size: 0.7rem;
            line-height: 1.4;
            text-align: left;
            z-index: 50;
        }

        .info-icon:hover::after,
        .info-icon:focus-visible::after {
            opacity: 1;
            transform: translate(-50%, -2px);
        }

        .info-icon:focus-visible {
            outline: 2px solid rgba(56, 189, 248, 0.7);
            outline-offset: 2px;
        }

        .heading-with-icon,
        .subheading-with-icon {
            display: flex;
            align-items: center;
            gap: 0.45rem;
        }

        .stat .value {
            display: block;
            margin-top: 0.35rem;
            font-size: 1.25rem;
            font-weight: 600;
        }

        .muted {
            color: #94a3b8;
            font-size: 0.88rem;
        }

        .list {
            list-style: none;
            padding: 0;
            margin: 0;
        }

        .list li {
            padding: 0.7rem 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.12);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }

        .list li:last-child {
            border-bottom: none;
        }

        .list li .text {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            min-width: 0;
        }

        .list li strong {
            font-size: 0.95rem;
        }

        .badge {
            background: rgba(56, 189, 248, 0.16);
            color: #bae6fd;
            padding: 0.25rem 0.7rem;
            border-radius: 999px;
            font-size: 0.65rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            white-space: nowrap;
        }

        .table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 0.9rem;
            font-size: 0.9rem;
        }

        .table thead {
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .table th,
        .table td {
            padding: 0.55rem 0.4rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.12);
            text-align: left;
        }

        .table tbody tr:last-child td {
            border-bottom: none;
        }

        button.refresh {
            background: transparent;
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 999px;
            color: inherit;
            padding: 0.45rem 1.1rem;
            cursor: pointer;
            transition: background 0.2s ease, border 0.2s ease, color 0.2s ease;
            font-size: 0.78rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        button.refresh:hover {
            background: rgba(56, 189, 248, 0.18);
            border-color: rgba(56, 189, 248, 0.65);
            color: #e0f2fe;
        }

        button.refresh:disabled {
            opacity: 0.6;
            cursor: wait;
        }

        .footer {
            text-align: center;
            padding: 3rem 1rem 2.5rem;
            color: #64748b;
            font-size: 0.85rem;
        }

        .fade-in {
            animation: fade-in 0.4s ease-in-out both;
        }

        @keyframes fade-in {
            from {
                opacity: 0;
                transform: translateY(8px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
    </style>
</head>
<body data-version="__PERONA_VERSION__">
    <header>
        <h1>Perona Operational Dashboard</h1>
        <p>A refreshed, responsive control surface for render telemetry, risk signals, and cost analytics backed by the Perona engine.</p>
    </header>
    <main>
        <div class="grid">
            <section class="card fade-in span-12">
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;">
                    <div>
                        <h2 class="heading-with-icon">
                            Overview
                            <span class="info-icon" tabindex="0" aria-label="High-level snapshot of current render health and operations." data-tooltip="High-level snapshot of current render health and operations."></span>
                        </h2>
                        <p class="muted">Data window <span id="summary-generated">—</span></p>
                    </div>
                    <button class="refresh" id="refresh-summary" type="button">Refresh data</button>
                </div>
                <p class="muted" id="summary-status" style="margin-top: 0.75rem;">Gathering metrics…</p>
                <div class="stat-grid">
                    <div class="stat">
                        <span class="label">
                            Render samples
                            <span class="info-icon" tabindex="0" aria-label="Number of telemetry samples captured in the current summary window." data-tooltip="Number of telemetry samples captured in the current summary window."></span>
                        </span>
                        <span class="value" id="metrics-total">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Average FPS
                            <span class="info-icon" tabindex="0" aria-label="Average frames rendered per second across monitored nodes." data-tooltip="Average frames rendered per second across monitored nodes."></span>
                        </span>
                        <span class="value" id="metrics-fps">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Frame time
                            <span class="info-icon" tabindex="0" aria-label="Average time taken to render a single frame." data-tooltip="Average time taken to render a single frame."></span>
                        </span>
                        <span class="value" id="metrics-frame-time">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            GPU utilisation
                            <span class="info-icon" tabindex="0" aria-label="Average proportion of GPU resources currently consumed by rendering." data-tooltip="Average proportion of GPU resources currently consumed by rendering."></span>
                        </span>
                        <span class="value" id="metrics-gpu">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Errors / sample
                            <span class="info-icon" tabindex="0" aria-label="Average number of errors captured in each telemetry sample." data-tooltip="Average number of errors captured in each telemetry sample."></span>
                        </span>
                        <span class="value" id="metrics-errors">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Critical risks
                            <span class="info-icon" tabindex="0" aria-label="Count of shots currently flagged with critical risk signals." data-tooltip="Count of shots currently flagged with critical risk signals."></span>
                        </span>
                        <span class="value" id="risk-critical">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Active shots
                            <span class="info-icon" tabindex="0" aria-label="Number of shots currently in progress across the pipeline." data-tooltip="Number of shots currently in progress across the pipeline."></span>
                        </span>
                        <span class="value" id="shots-active">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Spend delta
                            <span class="info-icon" tabindex="0" aria-label="Difference between baseline and current render spending." data-tooltip="Difference between baseline and current render spending."></span>
                        </span>
                        <span class="value" id="costs-delta">—</span>
                    </div>
                </div>
                <p class="muted" style="margin-top: 1.1rem;">
                    Latest telemetry sample: <span id="metrics-latest">—</span>
                </p>
            </section>

            <section class="card fade-in span-6">
                <h2 class="heading-with-icon">
                    Shot progress
                    <span class="info-icon" tabindex="0" aria-label="Breakdown of monitored shots across stages and sequences." data-tooltip="Breakdown of monitored shots across stages and sequences."></span>
                </h2>
                <p class="muted">Total <strong id="shots-total">—</strong> • Completed <strong id="shots-completed">—</strong></p>
                <h3 class="subheading-with-icon">
                    By stage
                    <span class="info-icon" tabindex="0" aria-label="Shot counts grouped by production stage." data-tooltip="Shot counts grouped by production stage."></span>
                </h3>
                <ul class="list" id="shots-by-stage"></ul>
                <h3 class="subheading-with-icon">
                    By sequence
                    <span class="info-icon" tabindex="0" aria-label="Shot counts grouped by sequence or episode." data-tooltip="Shot counts grouped by sequence or episode."></span>
                </h3>
                <ul class="list" id="shots-by-sequence"></ul>
            </section>

            <section class="card fade-in span-6">
                <h2 class="heading-with-icon">
                    Active focus shots
                    <span class="info-icon" tabindex="0" aria-label="Shots currently flagged for additional attention or follow-up." data-tooltip="Shots currently flagged for additional attention or follow-up."></span>
                </h2>
                <ul class="list" id="active-shots"></ul>
            </section>

            <section class="card fade-in span-6">
                <h2 class="heading-with-icon">
                    Risk outlook
                    <span class="info-icon" tabindex="0" aria-label="Current distribution of render risk indicators." data-tooltip="Current distribution of render risk indicators."></span>
                </h2>
                <p class="muted">Tracked <strong id="risk-count">—</strong> • Avg risk <strong id="risk-average">—</strong> • Range <strong id="risk-range">—</strong></p>
                <h3 class="subheading-with-icon">
                    Top signals
                    <span class="info-icon" tabindex="0" aria-label="Highest severity risk signals requiring action." data-tooltip="Highest severity risk signals requiring action."></span>
                </h3>
                <ul class="list" id="risk-top"></ul>
            </section>

            <section class="card fade-in span-6">
                <h2 class="heading-with-icon">
                    Cost profile
                    <span class="info-icon" tabindex="0" aria-label="Snapshot of baseline versus current render spend." data-tooltip="Snapshot of baseline versus current render spend."></span>
                </h2>
                <div class="stat-grid" style="margin-top: 1rem;">
                    <div class="stat">
                        <span class="label">
                            Baseline
                            <span class="info-icon" tabindex="0" aria-label="Total planned spending for the comparison period." data-tooltip="Total planned spending for the comparison period."></span>
                        </span>
                        <span class="value" id="costs-baseline">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Current
                            <span class="info-icon" tabindex="0" aria-label="Actual cost accumulated for the current period." data-tooltip="Actual cost accumulated for the current period."></span>
                        </span>
                        <span class="value" id="costs-current">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Delta
                            <span class="info-icon" tabindex="0" aria-label="Difference between baseline and current total spend." data-tooltip="Difference between baseline and current total spend."></span>
                        </span>
                        <span class="value" id="costs-total-delta">—</span>
                    </div>
                    <div class="stat">
                        <span class="label">
                            Cost / frame
                            <span class="info-icon" tabindex="0" aria-label="Baseline, current, and delta cost required to render a single frame." data-tooltip="Baseline, current, and delta cost required to render a single frame."></span>
                        </span>
                        <span class="value" id="costs-per-frame">—</span>
                    </div>
                </div>
                <h3 class="subheading-with-icon">
                    Top contributors
                    <span class="info-icon" tabindex="0" aria-label="Factors driving the largest changes in spending." data-tooltip="Factors driving the largest changes in spending."></span>
                </h3>
                <ul class="list" id="cost-contributors"></ul>
            </section>

            <section class="card fade-in span-12">
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;">
                    <h2 class="heading-with-icon" style="margin: 0;">
                        Live render feed
                        <span class="info-icon" tabindex="0" aria-label="Streaming telemetry of the most recent render events." data-tooltip="Streaming telemetry of the most recent render events."></span>
                    </h2>
                    <span class="badge" id="metrics-stream-badge">Connecting</span>
                </div>
                <table class="table" aria-live="polite">
                    <thead>
                        <tr>
                            <th>Sequence</th>
                            <th>Shot</th>
                            <th>FPS</th>
                            <th>Frame time (ms)</th>
                            <th>Timestamp</th>
                        </tr>
                    </thead>
                    <tbody id="metrics-stream-rows"></tbody>
                </table>
                <p class="muted" id="metrics-stream-status">Attempting to open a WebSocket connection…</p>
            </section>
        </div>
    </main>
    <footer class="footer">
        <span id="version-label">Perona v__PERONA_VERSION__</span>
    </footer>
    <script>
        (() => {
            const summaryEndpoint = new URL(
                "./dashboard/summary",
                window.location.href,
            ).toString();
            const AUTO_REFRESH_INTERVAL_MS = 60000;
            let autoRefreshTimer;

            const elements = {
                summaryGenerated: document.getElementById("summary-generated"),
                summaryStatus: document.getElementById("summary-status"),
                metricsTotal: document.getElementById("metrics-total"),
                metricsFps: document.getElementById("metrics-fps"),
                metricsFrameTime: document.getElementById("metrics-frame-time"),
                metricsGpu: document.getElementById("metrics-gpu"),
                metricsErrors: document.getElementById("metrics-errors"),
                metricsLatest: document.getElementById("metrics-latest"),
                shotsActive: document.getElementById("shots-active"),
                shotsTotal: document.getElementById("shots-total"),
                shotsCompleted: document.getElementById("shots-completed"),
                costsDelta: document.getElementById("costs-delta"),
                costsBaseline: document.getElementById("costs-baseline"),
                costsCurrent: document.getElementById("costs-current"),
                costsTotalDelta: document.getElementById("costs-total-delta"),
                costsPerFrame: document.getElementById("costs-per-frame"),
                riskCritical: document.getElementById("risk-critical"),
                riskCount: document.getElementById("risk-count"),
                riskAverage: document.getElementById("risk-average"),
                riskRange: document.getElementById("risk-range"),
                shotsByStage: document.getElementById("shots-by-stage"),
                shotsBySequence: document.getElementById("shots-by-sequence"),
                activeShots: document.getElementById("active-shots"),
                riskTop: document.getElementById("risk-top"),
                costContributors: document.getElementById("cost-contributors"),
                streamBadge: document.getElementById("metrics-stream-badge"),
                streamStatus: document.getElementById("metrics-stream-status"),
                streamRows: document.getElementById("metrics-stream-rows"),
                versionLabel: document.getElementById("version-label"),
            };

            const refreshButton = document.getElementById("refresh-summary");

            const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
                dateStyle: "medium",
                timeStyle: "short",
            });
            const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

            const formatNumber = (value, options) => {
                if (value === null || value === undefined) {
                    return "—";
                }
                return new Intl.NumberFormat(undefined, options ?? { maximumFractionDigits: 0 }).format(value);
            };

            const formatRatio = (value) => {
                if (value === null || value === undefined) {
                    return "—";
                }
                return new Intl.NumberFormat(undefined, {
                    style: "percent",
                    maximumFractionDigits: 0,
                }).format(value);
            };

            const formatPercent = (value) => {
                if (value === null || value === undefined) {
                    return "—";
                }
                return `${value.toFixed(0)}%`;
            };

            const formatCurrency = (value, currency, fractionDigits = 2) => {
                if (value === null || value === undefined) {
                    return "—";
                }
                if (!currency) {
                    return formatNumber(value, {
                        minimumFractionDigits: fractionDigits,
                        maximumFractionDigits: fractionDigits,
                    });
                }
                try {
                    return new Intl.NumberFormat(undefined, {
                        style: "currency",
                        currency,
                        minimumFractionDigits: fractionDigits,
                        maximumFractionDigits: fractionDigits,
                    }).format(value);
                } catch (error) {
                    return `${currency} ${value.toFixed(fractionDigits)}`;
                }
            };

            const formatFrameTime = (value) => {
                if (value === null || value === undefined) {
                    return "—";
                }
                return `${value.toFixed(1)} ms`;
            };

            const formatDateTime = (value) => {
                if (!value) {
                    return "—";
                }
                const date = new Date(value);
                if (Number.isNaN(date.getTime())) {
                    return value;
                }
                return dateTimeFormatter.format(date);
            };

            const formatRelative = (value) => {
                if (!value) {
                    return "";
                }
                const date = new Date(value);
                if (Number.isNaN(date.getTime())) {
                    return "";
                }
                const diffMs = date.getTime() - Date.now();
                const absMs = Math.abs(diffMs);
                if (absMs < 60_000) {
                    return relativeFormatter.format(Math.round(diffMs / 1_000), "second");
                }
                if (absMs < 3_600_000) {
                    return relativeFormatter.format(Math.round(diffMs / 60_000), "minute");
                }
                if (absMs < 86_400_000) {
                    return relativeFormatter.format(Math.round(diffMs / 3_600_000), "hour");
                }
                return relativeFormatter.format(Math.round(diffMs / 86_400_000), "day");
            };

            const formatTimestamp = (value) => {
                const absolute = formatDateTime(value);
                const relative = formatRelative(value);
                if (!relative) {
                    return absolute;
                }
                return `${absolute} • ${relative}`;
            };

            const updateList = (listElement, items, emptyMessage, builder) => {
                if (!listElement) {
                    return;
                }

                listElement.innerHTML = "";
                if (!items || !items.length) {
                    const li = document.createElement("li");
                    li.className = "muted";
                    li.textContent = emptyMessage;
                    listElement.appendChild(li);
                    return;
                }

                for (const item of items) {
                    const details = builder(item) ?? {};
                    const li = document.createElement("li");
                    const text = document.createElement("div");
                    text.className = "text";

                    if (details.title) {
                        const title = document.createElement("strong");
                        title.textContent = details.title;
                        text.appendChild(title);
                    }

                    if (details.subtitle) {
                        const subtitle = document.createElement("span");
                        subtitle.className = "muted";
                        subtitle.textContent = details.subtitle;
                        text.appendChild(subtitle);
                    }

                    li.appendChild(text);

                    if (details.badge) {
                        const badge = document.createElement("span");
                        badge.className = "badge";
                        badge.textContent = details.badge;
                        li.appendChild(badge);
                    } else if (details.value) {
                        const value = document.createElement("span");
                        value.textContent = details.value;
                        li.appendChild(value);
                    }

                    listElement.appendChild(li);
                }
            };

            const applySummary = (summary) => {
                const metrics = summary.metrics ?? {};
                const shots = summary.shots ?? {};
                const risk = summary.risk ?? {};
                const costs = summary.costs ?? {};

                elements.summaryGenerated.textContent = formatTimestamp(summary.generated_at);
                elements.summaryStatus.textContent = "Last refreshed moments ago.";

                elements.metricsTotal.textContent = formatNumber(metrics.total_samples);
                elements.metricsFps.textContent = formatNumber(metrics.average_fps, { maximumFractionDigits: 2 });
                elements.metricsFrameTime.textContent = formatFrameTime(metrics.average_frame_time_ms);
                elements.metricsGpu.textContent = formatRatio(metrics.average_gpu_utilisation);
                elements.metricsErrors.textContent = formatNumber(metrics.average_error_count, { maximumFractionDigits: 2 });
                elements.metricsLatest.textContent = metrics.latest_sample
                    ? `${metrics.latest_sample.sequence ?? "—"} ${metrics.latest_sample.shot_id ?? ""} • ${formatDateTime(metrics.latest_sample.timestamp)}`
                    : "No recent telemetry";

                elements.shotsActive.textContent = formatNumber(shots.active);
                elements.shotsTotal.textContent = formatNumber(shots.total);
                elements.shotsCompleted.textContent = formatNumber(shots.completed);

                elements.riskCritical.textContent = formatNumber(risk.critical_count);
                elements.riskCount.textContent = formatNumber(risk.count);
                elements.riskAverage.textContent = formatPercent(risk.average_risk ?? null);
                elements.riskRange.textContent = `${formatPercent(risk.min_risk ?? null)} – ${formatPercent(risk.max_risk ?? null)}`;

                elements.costsDelta.textContent = formatCurrency(costs.delta_total_cost, costs.currency);
                elements.costsBaseline.textContent = formatCurrency(costs.baseline_total_cost, costs.currency);
                elements.costsCurrent.textContent = formatCurrency(costs.current_total_cost, costs.currency);
                elements.costsTotalDelta.textContent = formatCurrency(costs.delta_total_cost, costs.currency);
                elements.costsPerFrame.textContent = [
                    formatCurrency(costs.baseline_cost_per_frame, costs.currency, 4),
                    formatCurrency(costs.current_cost_per_frame, costs.currency, 4),
                    formatCurrency(costs.delta_cost_per_frame, costs.currency, 4),
                ].join(" / ");

                updateList(elements.shotsByStage, shots.by_stage, "No stage data yet", (entry) => ({
                    title: entry.name ?? "Unknown stage",
                    value: `${formatNumber(entry.shots)} shots`,
                }));

                updateList(elements.shotsBySequence, shots.by_sequence, "No sequences tracked", (entry) => ({
                    title: entry.name ?? "Sequence",
                    value: `${formatNumber(entry.shots)} shots`,
                }));

                updateList(elements.activeShots, shots.notable_active, "No active focus shots", (shot) => {
                    const subtitleParts = [];
                    if (shot.stage_metrics) {
                        subtitleParts.push(String(shot.stage_metrics));
                    }
                    if (shot.stage_started_at) {
                        subtitleParts.push(`since ${formatDateTime(shot.stage_started_at)}`);
                    }
                    return {
                        title: `${shot.sequence ?? "—"} ${shot.shot_id ?? ""}`.trim(),
                        subtitle: subtitleParts.join(" • ") || undefined,
                        badge: shot.current_stage ?? "—",
                    };
                });

                updateList(elements.riskTop, risk.top_risks, "No high-risk shots", (item) => ({
                    title: `${item.sequence ?? "—"} ${item.shot_id ?? ""}`.trim(),
                    subtitle: item.drivers ?? undefined,
                    value: formatPercent(item.risk_score ?? null),
                }));

                updateList(elements.costContributors, costs.top_contributors, "No contributing factors identified", (item) => ({
                    title: item.factor ?? "Unknown factor",
                    value: formatCurrency(item.delta_cost, costs.currency),
                }));
            };

            const fetchSummary = async () => {
                const response = await fetch(summaryEndpoint, {
                    headers: { Accept: "application/json" },
                    cache: "no-cache",
                });
                if (!response.ok) {
                    throw new Error(`Failed to load summary (${response.status})`);
                }
                return await response.json();
            };

            const scheduleAutoRefresh = () => {
                if (!Number.isFinite(AUTO_REFRESH_INTERVAL_MS) || AUTO_REFRESH_INTERVAL_MS <= 0) {
                    return;
                }
                if (autoRefreshTimer) {
                    window.clearTimeout(autoRefreshTimer);
                }
                autoRefreshTimer = window.setTimeout(() => {
                    refreshSummary().catch((error) => {
                        console.error(error);
                    });
                }, AUTO_REFRESH_INTERVAL_MS);
            };

            const refreshSummary = async () => {
                if (refreshButton) {
                    refreshButton.disabled = true;
                    refreshButton.textContent = "Refreshing…";
                }
                elements.summaryStatus.textContent = "Refreshing data…";
                try {
                    const summary = await fetchSummary();
                    applySummary(summary);
                    elements.summaryStatus.textContent = "Dashboard synchronised.";
                } catch (error) {
                    console.error(error);
                    elements.summaryStatus.textContent = "Unable to refresh summary data.";
                } finally {
                    if (refreshButton) {
                        refreshButton.disabled = false;
                        refreshButton.textContent = "Refresh data";
                    }
                    scheduleAutoRefresh();
                }
            };

            if (refreshButton) {
                refreshButton.addEventListener("click", () => void refreshSummary());
            }

            if (elements.versionLabel) {
                const version = document.body.dataset.version;
                elements.versionLabel.textContent = `Perona v${version}`;
            }

            const startMetricsStream = () => {
                const { streamBadge, streamStatus, streamRows } = elements;
                if (!("WebSocket" in window)) {
                    streamBadge.textContent = "Offline";
                    streamStatus.textContent = "WebSockets are not supported in this browser.";
                    return;
                }

                const protocol = window.location.protocol === "https:" ? "wss" : "ws";
                const url = `${protocol}://${window.location.host}/ws/metrics`;
                let reconnectTimer;

                const connect = () => {
                    const socket = new WebSocket(url);
                    streamBadge.textContent = "Connecting";
                    streamStatus.textContent = "Attempting to open a WebSocket connection…";

                    socket.addEventListener("open", () => {
                        streamBadge.textContent = "Live";
                        streamStatus.textContent = "Streaming live render metrics.";
                    });

                    socket.addEventListener("message", (event) => {
                        try {
                            const sample = JSON.parse(event.data ?? "{}");
                            const row = document.createElement("tr");
                            row.innerHTML = `
                                <td>${sample.sequence ?? "—"}</td>
                                <td>${sample.shot_id ?? "—"}</td>
                                <td>${formatNumber(sample.fps, { maximumFractionDigits: 1 })}</td>
                                <td>${formatNumber(sample.frame_time_ms, { maximumFractionDigits: 0 })}</td>
                                <td>${formatDateTime(sample.timestamp)}</td>
                            `;
                            if (streamRows.firstChild) {
                                streamRows.insertBefore(row, streamRows.firstChild);
                            } else {
                                streamRows.appendChild(row);
                            }
                            const maxRows = 12;
                            while (streamRows.children.length > maxRows) {
                                streamRows.removeChild(streamRows.lastChild);
                            }
                        } catch (error) {
                            console.error("Failed to render metrics sample", error);
                        }
                    });

                    const scheduleReconnect = () => {
                        if (reconnectTimer) {
                            window.clearTimeout(reconnectTimer);
                        }
                        reconnectTimer = window.setTimeout(() => {
                            connect();
                        }, 4000);
                    };

                    socket.addEventListener("close", () => {
                        streamBadge.textContent = "Paused";
                        streamStatus.textContent = "Live stream disconnected. Reconnecting shortly…";
                        scheduleReconnect();
                    });

                    socket.addEventListener("error", () => {
                        streamBadge.textContent = "Offline";
                        streamStatus.textContent = "Unable to connect to the render feed.";
                        socket.close();
                    });
                };

                connect();
            };

            refreshSummary().catch((error) => {
                console.error(error);
            });
            startMetricsStream();
        })();
    </script>
</body>
</html>
"""

    return template.replace("__PERONA_VERSION__", PERONA_VERSION)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard_ui() -> HTMLResponse:
    """Serve the modern Perona dashboard HTML shell."""

    return HTMLResponse(content=_dashboard_index_html())


@app.post("/api/metrics", status_code=status.HTTP_202_ACCEPTED)
async def ingest_render_metrics(
    payload: RenderMetricBatch, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Accept render metrics and persist them asynchronously."""

    records = payload.to_serialisable()
    if not records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No metrics supplied."
        )

    background_tasks.add_task(_metrics_store.persist, records)
    return {"status": "accepted", "enqueued": len(records)}


def _lifecycle_date_bounds(lifecycle: ShotLifecycle) -> tuple[datetime, datetime]:
    """Return the earliest start and latest activity timestamps for a lifecycle."""

    starts = [stage.started_at for stage in lifecycle.stages]
    now = datetime.utcnow()
    ends = [stage.completed_at or now for stage in lifecycle.stages]
    return min(starts), max(ends)


def _filter_lifecycles(
    lifecycles: Sequence[ShotLifecycle],
    sequence: str | None,
    artist: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
) -> list[ShotLifecycle]:
    """Filter lifecycles using the supplied query parameters."""

    artist_lower = artist.lower() if artist else None

    filtered: list[ShotLifecycle] = []
    for lifecycle in lifecycles:
        if sequence and lifecycle.sequence != sequence:
            continue

        if artist_lower:
            matches_artist = any(
                isinstance(stage.metrics.get("artist"), str)
                and stage.metrics["artist"].lower() == artist_lower
                for stage in lifecycle.stages
            )
            if not matches_artist:
                continue

        if start_date or end_date:
            first_activity, last_activity = _lifecycle_date_bounds(lifecycle)
            if start_date and last_activity < start_date:
                continue
            if end_date and first_activity > end_date:
                continue

        filtered.append(lifecycle)

    return filtered


class _CostInsightsMemo:
    """In-memory cache for cost insights keyed by ``top_n``."""

    __slots__ = ("statistics", "recommendations_by_top_n")

    def __init__(self) -> None:
        self.statistics: tuple[FeatureStatistics, ...] | None = None
        self.recommendations_by_top_n: dict[int, tuple[str, ...]] = {}

    def clear(self) -> None:
        self.statistics = None
        self.recommendations_by_top_n.clear()


class _EngineCacheEntry(NamedTuple):
    engine: PeronaEngine
    signature: tuple[str | None, str, int | None]
    settings_path: Path | None
    warnings: tuple[str, ...]
    insights: _CostInsightsMemo


_engine_lock = Lock()
_engine_cache: _EngineCacheEntry | None = None


def _resolved_settings_path() -> Path | None:
    """Return the first existing settings candidate for display purposes."""

    env_path = os.getenv("PERONA_SETTINGS_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(DEFAULT_SETTINGS_PATH)

    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved
    return None


def _settings_signature() -> tuple[str | None, str, int | None]:
    """Return the cache signature for the current settings configuration."""

    env_path = os.getenv("PERONA_SETTINGS_PATH")
    resolved_path = _resolved_settings_path()
    signature_path = resolved_path or DEFAULT_SETTINGS_PATH.expanduser()

    mtime_ns: int | None = None
    try:
        stat_result = signature_path.stat()
        mtime_ns = getattr(stat_result, "st_mtime_ns", None)
        if mtime_ns is None:
            mtime_ns = int(stat_result.st_mtime * 1_000_000_000)
    except OSError:
        mtime_ns = None

    return (env_path, str(signature_path), mtime_ns)


def _get_engine_cache_entry(force_refresh: bool = False) -> _EngineCacheEntry:
    """Return the cached engine entry, refreshing when configuration changes."""

    global _engine_cache

    signature = _settings_signature()
    with _engine_lock:
        cache_entry = _engine_cache
        if force_refresh or cache_entry is None or cache_entry.signature != signature:
            load_result = PeronaEngine.from_settings()
            cache_entry = _EngineCacheEntry(
                engine=load_result.engine,
                signature=signature,
                settings_path=load_result.settings_path,
                warnings=load_result.warnings,
                insights=_CostInsightsMemo(),
            )
            _engine_cache = cache_entry
        return cache_entry


def _load_engine(force_refresh: bool) -> PeronaEngine:
    """Return a cached engine instance, reloading when configuration changes."""

    return _get_engine_cache_entry(force_refresh).engine


def invalidate_engine_cache() -> None:
    """Clear the cached engine so it will be rebuilt on next use."""

    global _engine_cache
    with _engine_lock:
        _engine_cache = None


def _resolve_cost_insights(
    engine: PeronaEngine,
    *,
    top_n: int,
    refresh_telemetry: bool,
) -> tuple[tuple[FeatureStatistics, ...], tuple[str, ...]]:
    """Return cost insights using cached results when available."""

    cached_statistics: tuple[FeatureStatistics, ...] | None = None
    cached_recommendations: tuple[str, ...] | None = None

    with _engine_lock:
        cache_entry = _engine_cache
        if cache_entry is not None and cache_entry.engine is engine:
            if refresh_telemetry:
                cache_entry.insights.clear()
            memo = cache_entry.insights
            cached_statistics = memo.statistics
            cached_recommendations = memo.recommendations_by_top_n.get(top_n)
            if cached_statistics is not None and cached_recommendations is not None:
                return cached_statistics, cached_recommendations

    statistics, recommendations = engine.cost_insights(top_n=top_n)

    with _engine_lock:
        cache_entry = _engine_cache
        if cache_entry is not None and cache_entry.engine is engine:
            memo = cache_entry.insights
            memo.statistics = statistics
            memo.recommendations_by_top_n[top_n] = recommendations

    return statistics, recommendations


def _settings_summary_from_cache(force_refresh: bool = False) -> SettingsSummary:
    """Return a settings summary derived from the cached engine entry."""

    cache_entry = _get_engine_cache_entry(force_refresh)
    return SettingsSummary.from_engine(
        cache_entry.engine,
        settings_path=cache_entry.settings_path,
        warnings=cache_entry.warnings,
    )


def reload_settings() -> SettingsSummary:
    """Invalidate and rebuild the engine cache, returning the refreshed summary."""

    invalidate_engine_cache()
    return _settings_summary_from_cache(force_refresh=True)


def get_engine(refresh: bool = Query(False, alias="refresh_engine")) -> PeronaEngine:
    """FastAPI dependency yielding the shared Perona engine instance."""

    return _load_engine(refresh)


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health endpoint for uptime checks."""

    return {"status": "ok"}


@app.get("/settings", response_model=SettingsSummary)
def settings_summary() -> SettingsSummary:
    """Return the resolved configuration powering the dashboard."""

    return _settings_summary_from_cache()


@app.post("/settings/reload", response_model=SettingsSummary)
def settings_reload() -> SettingsSummary:
    """Reload engine configuration and return the updated settings summary."""

    return reload_settings()


@app.get("/render-feed", response_model=list[RenderMetric])
def render_feed(
    limit: int = Query(30, ge=1, le=250),
    sequence: str | None = Query(None),
    shot_id: str | None = Query(None),
    engine: PeronaEngine = Depends(get_engine),
) -> list[RenderMetric]:
    """Return recent render telemetry samples for dashboard widgets."""

    metrics = [
        RenderMetric.from_entity(metric)
        for metric in engine.stream_render_metrics(
            limit, sequence=sequence, shot_id=shot_id
        )
    ]
    return metrics


@app.get("/render-feed/live")
async def render_feed_stream(
    limit: int = Query(30, ge=1, le=250),
    sequence: str | None = Query(None),
    shot_id: str | None = Query(None),
    engine: PeronaEngine = Depends(get_engine),
) -> StreamingResponse:
    """Stream telemetry samples using newline delimited JSON."""

    async def _generator() -> Any:
        for metric in engine.stream_render_metrics(
            limit, sequence=sequence, shot_id=shot_id
        ):
            model = RenderMetric.from_entity(metric)
            payload = model.model_dump(mode="json", by_alias=True)
            yield json.dumps(payload) + "\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(_generator(), media_type="application/x-ndjson")


@app.get("/metrics")
def metrics_summary(engine: PeronaEngine = Depends(get_engine)) -> dict[str, Any]:
    """Return aggregated statistics for recent render telemetry."""

    def _rounded_mean(total: float, count: int) -> float:
        return round(total / count, 3) if count else 0.0

    total_samples = 0
    total_fps = 0.0
    total_frame_time = 0.0
    total_gpu_utilisation = 0.0
    total_error_count = 0.0

    sequence_stats: dict[str, dict[str, Any]] = {}
    latest_sample: RenderMetric | None = None
    latest_timestamp: datetime | None = None

    for sample in engine.stream_render_metrics():
        total_samples += 1
        total_fps += sample.fps
        total_frame_time += sample.frame_time_ms
        total_gpu_utilisation += sample.gpu_utilisation
        total_error_count += sample.error_count

        entry = sequence_stats.setdefault(
            sample.sequence,
            {
                "shots": set(),
                "count": 0,
                "fps_total": 0.0,
                "frame_time_total": 0.0,
                "gpu_utilisation_total": 0.0,
                "error_total": 0.0,
            },
        )
        entry["shots"].add(sample.shot_id)
        entry["count"] += 1
        entry["fps_total"] += sample.fps
        entry["frame_time_total"] += sample.frame_time_ms
        entry["gpu_utilisation_total"] += sample.gpu_utilisation
        entry["error_total"] += sample.error_count

        if latest_timestamp is None or sample.timestamp > latest_timestamp:
            latest_timestamp = sample.timestamp
            latest_sample = sample

    if total_samples == 0:
        return {
            "total_samples": 0,
            "averages": {
                "fps": 0.0,
                "frame_time_ms": 0.0,
                "gpu_utilisation": 0.0,
                "error_count": 0.0,
            },
            "sequences": [],
            "latest_sample": None,
        }

    overall_averages = {
        "fps": _rounded_mean(total_fps, total_samples),
        "frame_time_ms": _rounded_mean(total_frame_time, total_samples),
        "gpu_utilisation": _rounded_mean(total_gpu_utilisation, total_samples),
        "error_count": _rounded_mean(total_error_count, total_samples),
    }

    sequences_summary = [
        {
            "sequence": name,
            "shots": len(data["shots"]),
            "avg_fps": _rounded_mean(data["fps_total"], data["count"]),
            "avg_frame_time_ms": _rounded_mean(data["frame_time_total"], data["count"]),
            "avg_gpu_utilisation": _rounded_mean(
                data["gpu_utilisation_total"], data["count"]
            ),
            "avg_error_count": _rounded_mean(data["error_total"], data["count"]),
        }
        for name, data in sorted(sequence_stats.items())
    ]

    latest_payload = (
        RenderMetric.from_entity(latest_sample).model_dump(mode="json", by_alias=True)
        if latest_sample
        else None
    )

    return {
        "total_samples": total_samples,
        "averages": overall_averages,
        "sequences": sequences_summary,
        "latest_sample": latest_payload,
    }


@app.post("/cost/estimate", response_model=CostEstimate)
def cost_estimate(
    payload: CostEstimateRequest,
    engine: PeronaEngine = Depends(get_engine),
) -> CostEstimate:
    """Estimate the cost per frame for the supplied inputs."""

    breakdown = engine.estimate_cost(payload.to_entity())
    return CostEstimate.from_breakdown(breakdown)


@app.get("/api/cost/insights", response_model=CostInsightResponse)
def cost_insights(
    top_n: int = Query(3, ge=1, le=10),
    refresh_telemetry: bool = Query(
        False, alias="refresh_telemetry", description="Reload persisted telemetry"
    ),
    engine: PeronaEngine = Depends(get_engine),
) -> CostInsightResponse:
    """Return descriptive statistics and optimisation suggestions."""

    statistics, recommendations = _resolve_cost_insights(
        engine, top_n=top_n, refresh_telemetry=refresh_telemetry
    )

    if not statistics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No telemetry statistics available.",
        )

    cache_entry = _get_engine_cache_entry()
    return CostInsightResponse.from_results(
        statistics,
        recommendations,
        settings_path=cache_entry.settings_path,
    )


@app.get("/risk-heatmap", response_model=list[RiskIndicator])
def risk_heatmap(
    engine: PeronaEngine = Depends(get_engine),
) -> list[RiskIndicator]:
    """Return the current render risk heatmap."""

    return [RiskIndicator.from_entity(item) for item in engine.risk_heatmap()]


@app.get("/pnl", response_model=PnLBreakdown)
def pnl(engine: PeronaEngine = Depends(get_engine)) -> PnLBreakdown:
    """Return the P&L attribution summary for the latest render window."""

    breakdown = engine.pnl_explainer()
    return PnLBreakdown.from_entity(breakdown)


@app.post("/optimization/backtest", response_model=OptimizationBacktestResponse)
def optimization_backtest(
    payload: OptimizationBacktestRequest,
    engine: PeronaEngine = Depends(get_engine),
) -> OptimizationBacktestResponse:
    """Run what-if optimisation scenarios and return their cost impact."""

    scenarios = [item.to_entity() for item in payload.scenarios]
    baseline, results = engine.run_optimization_backtest(scenarios)
    return OptimizationBacktestResponse(
        baseline=CostEstimate.from_breakdown(baseline),
        scenarios=tuple(OptimizationResult.from_entity(item) for item in results),
    )


@app.get("/shots/lifecycle", response_model=list[Shot])
def shots_lifecycle(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    engine: PeronaEngine = Depends(get_engine),
) -> list[Shot]:
    """Return lifecycle timelines for key monitored shots."""

    lifecycles = _filter_lifecycles(
        engine.shot_lifecycle(), sequence, artist, start_date, end_date
    )
    return [Shot.from_entity(item) for item in lifecycles]


@app.get("/shots/sequences", response_model=list[PeronaSequence])
def shot_sequences(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    engine: PeronaEngine = Depends(get_engine),
) -> list[PeronaSequence]:
    """Return monitored shots grouped by sequence."""

    lifecycles = _filter_lifecycles(
        engine.shot_lifecycle(), sequence, artist, start_date, end_date
    )
    sequences = sequences_from_lifecycles(lifecycles)
    return list(sequences)


@app.get("/shots")
def shots_summary(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    engine: PeronaEngine = Depends(get_engine),
) -> dict[str, Any]:
    """Return aggregated production status for monitored shots."""

    lifecycles = _filter_lifecycles(
        engine.shot_lifecycle(), sequence, artist, start_date, end_date
    )
    lifecycles = list(lifecycles)
    total = len(lifecycles)
    completed = sum(
        1
        for lifecycle in lifecycles
        if all(stage.completed_at is not None for stage in lifecycle.stages)
    )

    by_stage = Counter(lifecycle.current_stage for lifecycle in lifecycles)
    by_sequence = Counter(lifecycle.sequence for lifecycle in lifecycles)

    active_shots: list[dict[str, Any]] = []
    for lifecycle in lifecycles:
        if all(stage.completed_at is not None for stage in lifecycle.stages):
            continue
        current_stage_name = lifecycle.current_stage
        stage_details = next(
            (stage for stage in lifecycle.stages if stage.name == current_stage_name),
            None,
        )
        active_shots.append(
            {
                "sequence": lifecycle.sequence,
                "shot_id": lifecycle.shot_id,
                "current_stage": current_stage_name,
                "stage_started_at": stage_details.started_at if stage_details else None,
                "stage_completed_at": (
                    stage_details.completed_at if stage_details else None
                ),
                "stage_metrics": (
                    dict(stage_details.metrics) if stage_details is not None else {}
                ),
            }
        )

    active_shots.sort(key=lambda item: (item["sequence"], item["shot_id"]))

    return {
        "total": total,
        "completed": completed,
        "active": max(total - completed, 0),
        "by_sequence": [
            {"name": name, "shots": count}
            for name, count in sorted(by_sequence.items())
        ],
        "by_stage": [
            {"name": name, "shots": count} for name, count in by_stage.most_common()
        ],
        "active_shots": active_shots,
    }


@app.get("/risk")
def risk_summary(engine: PeronaEngine = Depends(get_engine)) -> dict[str, Any]:
    """Return risk score distribution for the monitored shot portfolio."""

    indicators = list(engine.risk_heatmap())
    if not indicators:
        return {
            "count": 0,
            "average_risk": 0.0,
            "max_risk": None,
            "min_risk": None,
            "top_risks": [],
            "critical": [],
        }

    average_risk = round(fmean(item.risk_score for item in indicators), 2)
    top_three = [
        RiskIndicator.from_entity(item).model_dump(mode="json")
        for item in indicators[:3]
    ]
    critical = [
        RiskIndicator.from_entity(item).model_dump(mode="json")
        for item in indicators
        if item.risk_score >= 75
    ]

    return {
        "count": len(indicators),
        "average_risk": average_risk,
        "max_risk": indicators[0].risk_score,
        "min_risk": indicators[-1].risk_score,
        "top_risks": top_three,
        "critical": critical,
    }


@app.get("/costs")
def costs_summary(engine: PeronaEngine = Depends(get_engine)) -> dict[str, Any]:
    """Return key spend metrics combining baseline and current projections."""

    baseline_input = engine.baseline_cost_input
    baseline_breakdown = engine.estimate_cost(baseline_input)
    pnl_breakdown = engine.pnl_explainer()

    baseline_payload = CostEstimate.from_breakdown(baseline_breakdown).model_dump(
        mode="json"
    )
    pnl_payload = PnLBreakdown.from_entity(pnl_breakdown).model_dump(mode="json")

    frame_count = max(baseline_breakdown.frame_count, 1)
    baseline_cost_per_frame = round(baseline_breakdown.cost_per_frame, 4)
    current_cost_per_frame = round(pnl_breakdown.current_cost / frame_count, 4)
    delta_cost_per_frame = round(current_cost_per_frame - baseline_cost_per_frame, 4)

    return {
        "baseline": baseline_payload,
        "pnl": pnl_payload,
        "currency": baseline_breakdown.currency,
        "cost_per_frame": {
            "baseline": baseline_cost_per_frame,
            "current": current_cost_per_frame,
            "delta": delta_cost_per_frame,
        },
    }


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


def _build_daily_summary(engine: PeronaEngine) -> dict[str, Any]:
    """Assemble the structured data used by the daily export."""

    generated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    metrics = metrics_summary(engine=engine)
    shots = shots_summary(
        sequence=None,
        artist=None,
        start_date=None,
        end_date=None,
        engine=engine,
    )
    risk = risk_summary(engine=engine)
    costs = costs_summary(engine=engine)

    averages = metrics.get("averages", {})
    latest_sample = metrics.get("latest_sample") or {}
    metrics_section: dict[str, Any] = {
        "total_samples": metrics.get("total_samples", 0),
        "average_fps": averages.get("fps", 0.0),
        "average_frame_time_ms": averages.get("frame_time_ms", 0.0),
        "average_gpu_utilisation": averages.get("gpu_utilisation", 0.0),
        "average_error_count": averages.get("error_count", 0.0),
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
        "metrics": metrics_section,
        "shots": shots_section,
        "risk": risk_section,
        "costs": costs_section,
    }


@app.get("/dashboard/summary")
def dashboard_summary(engine: PeronaEngine = Depends(get_engine)) -> dict[str, Any]:
    """Return the aggregated data backing the refreshed dashboard UI."""

    return _build_daily_summary(engine)


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


def _render_daily_csv(summary: Mapping[str, Any]) -> bytes:
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
    lines.append(
        "Risk Overview"
        f"  count={risk.get('count', 0)}, average={risk.get('average_risk', 0.0)}, "
        f"critical={risk.get('critical_count', 0)}"
    )
    top_risks = risk.get("top_risks", [])
    if top_risks:
        lines.append("  Top risks:")
        for item in top_risks:
            descriptor = (
                f"{item.get('sequence', 'N/A')} {item.get('shot_id', '')}"
                f" ({item.get('risk_score', 'N/A')})"
            )
            drivers = item.get("drivers")
            if drivers:
                descriptor += f" drivers: {drivers}"
            lines.append(f"    - {descriptor}")
    else:
        lines.append("  Top risks: None")

    lines.append("")
    lines.append("Cost Overview")
    lines.append(
        "  Baseline total: "
        + _format_currency(costs.get("baseline_total_cost"), currency)
    )
    lines.append(
        "  Current total: "
        + _format_currency(costs.get("current_total_cost"), currency)
    )
    lines.append(
        "  Delta total: " + _format_currency(costs.get("delta_total_cost"), currency)
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


def _render_daily_pdf(summary: Mapping[str, Any]) -> bytes:
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


@app.get("/reports/daily")
def daily_report(
    format: str = Query("csv"),
    engine: PeronaEngine = Depends(get_engine),
) -> StreamingResponse:
    """Generate a downloadable daily summary report in CSV or PDF format."""

    summary = _build_daily_summary(engine)
    fmt = format.lower()
    if fmt == "csv":
        payload = _render_daily_csv(summary)
        media_type = "text/csv"
        extension = "csv"
    elif fmt == "pdf":
        payload = _render_daily_pdf(summary)
        media_type = "application/pdf"
        extension = "pdf"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported format. Use 'csv' or 'pdf'.",
        )

    date_tag = summary["generated_at"].split("T", 1)[0]
    filename = f"perona_daily_summary_{date_tag}.{extension}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        iter([payload]),
        media_type=media_type,
        headers=headers,
    )


@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket) -> None:
    """Stream render telemetry samples over a WebSocket connection."""

    await websocket.accept()
    try:
        while True:
            engine = _load_engine(False)
            for sample in engine.stream_render_metrics(limit=30):
                payload = RenderMetric.from_entity(sample).model_dump(
                    mode="json", by_alias=True
                )
                await websocket.send_json(payload)
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


__all__ = ["app", "get_engine", "invalidate_engine_cache", "reload_settings"]
