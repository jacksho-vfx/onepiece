"""Templates used by the Perona dashboard web UI."""

from __future__ import annotations

from apps.perona.version import PERONA_VERSION


def dashboard_index_html() -> str:
    """Return the bundled HTML shell for the interactive dashboard."""

    template = """<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
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
            position: relative;
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

        .sr-only {
            position: absolute;
            width: 1px;
            height: 1px;
            padding: 0;
            margin: -1px;
            overflow: hidden;
            clip: rect(0, 0, 0, 0);
            border: 0;
            white-space: nowrap;
        }

        .wrangler-toggle {
            position: absolute;
            top: 1.5rem;
            right: 1.5rem;
            background: rgba(56, 189, 248, 0.16);
            color: #e0f2fe;
            border: 1px solid rgba(56, 189, 248, 0.35);
            border-radius: 999px;
            padding: 0.55rem 0.95rem;
            font-size: 0.9rem;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            cursor: pointer;
            transition: background 0.2s ease, border 0.2s ease, transform 0.2s ease;
        }

        .wrangler-toggle span[aria-hidden=\"true\"] {
            font-size: 1.15rem;
            line-height: 1;
        }

        .wrangler-toggle:hover {
            background: rgba(56, 189, 248, 0.24);
            border-color: rgba(125, 211, 252, 0.65);
            transform: translateY(-1px);
        }

        .wrangler-toggle:focus-visible {
            outline: 2px solid rgba(125, 211, 252, 0.9);
            outline-offset: 2px;
        }

        .wrangler-toggle:active {
            transform: translateY(1px);
        }

        .wrangler-overlay {
            position: fixed;
            inset: 0;
            background: rgba(15, 23, 42, 0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 1.5rem;
            z-index: 10;
        }

        .wrangler-menu {
            background: rgba(30, 41, 59, 0.95);
            border-radius: 1rem;
            box-shadow: 0 24px 48px rgba(15, 23, 42, 0.7);
            border: 1px solid rgba(148, 163, 184, 0.2);
            max-width: 520px;
            width: min(520px, 100%);
            color: inherit;
            display: grid;
            grid-template-rows: auto 1fr;
            max-height: min(540px, 80vh);
        }

        .wrangler-menu-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.15);
        }

        .wrangler-menu-title {
            margin: 0;
            font-size: 1.15rem;
        }

        .wrangler-close {
            background: transparent;
            color: inherit;
            border: none;
            font-size: 1.75rem;
            cursor: pointer;
            padding: 0.25rem 0.5rem;
            border-radius: 0.5rem;
        }

        .wrangler-close:hover,
        .wrangler-close:focus-visible {
            background: rgba(148, 163, 184, 0.1);
        }

        .wrangler-menu-body {
            padding: 1.5rem;
            overflow-y: auto;
        }

        .muted {
            color: #94a3b8;
        }

        .wrangler-menu-list {
            list-style: none;
            padding: 0;
            margin: 0;
            display: grid;
            gap: 0.75rem;
        }

        .wrangler-menu-item {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(148, 163, 184, 0.15);
            padding: 0.85rem 1rem;
            border-radius: 0.75rem;
            display: grid;
            gap: 0.35rem;
            transition: transform 0.2s ease, border 0.2s ease, background 0.2s ease;
        }

        .wrangler-menu-item:hover,
        .wrangler-menu-item:focus-within {
            border-color: rgba(125, 211, 252, 0.4);
            background: rgba(30, 41, 59, 0.75);
            transform: translateY(-1px);
        }

        .wrangler-menu-item h3 {
            margin: 0;
            font-size: 1rem;
        }

        .wrangler-menu-item p {
            margin: 0;
            font-size: 0.9rem;
        }

        .wrangler-menu-item button {
            justify-self: start;
            background: rgba(56, 189, 248, 0.2);
            border: 1px solid rgba(56, 189, 248, 0.4);
            color: #e0f2fe;
            border-radius: 999px;
            padding: 0.45rem 0.85rem;
            font-size: 0.85rem;
            cursor: pointer;
        }

        .wrangler-menu-item button:hover,
        .wrangler-menu-item button:focus-visible {
            background: rgba(56, 189, 248, 0.3);
            border-color: rgba(125, 211, 252, 0.6);
        }

        main {
            padding: 0 1.5rem 3rem;
            display: grid;
            gap: 1.5rem;
        }

        .grid {
            display: grid;
            gap: 1.5rem;
        }

        @media (min-width: 768px) {
            .grid {
                grid-template-columns: repeat(16, minmax(0, 1fr));
            }
        }

        .card {
            background: rgba(15, 23, 42, 0.75);
            border-radius: 1.25rem;
            border: 1px solid rgba(148, 163, 184, 0.2);
            box-shadow: 0 24px 48px rgba(15, 23, 42, 0.6);
            padding: 1.75rem;
            backdrop-filter: blur(18px);
        }

        .span-4 {
            grid-column: span 4;
        }

        .span-8 {
            grid-column: span 8;
        }

        .span-12 {
            grid-column: span 12;
        }

        .span-16 {
            grid-column: span 16;
        }

        @media (max-width: 1024px) {
            .span-4,
            .span-8,
            .span-12 {
                grid-column: span 16;
            }
        }

        .heading-with-icon {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            font-size: 1.1rem;
            margin: 0;
        }

        .info-icon {
            width: 1.1rem;
            height: 1.1rem;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.35);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8rem;
            color: rgba(15, 23, 42, 0.92);
            cursor: help;
            position: relative;
        }

        .info-icon::after {
            content: attr(data-tooltip);
            position: absolute;
            left: 50%;
            transform: translate(-50%, 8px);
            background: rgba(15, 23, 42, 0.95);
            color: #e2e8f0;
            padding: 0.5rem 0.75rem;
            border-radius: 0.75rem;
            box-shadow: 0 8px 16px rgba(15, 23, 42, 0.5);
            font-size: 0.75rem;
            width: max-content;
            max-width: 260px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s ease, transform 0.2s ease;
            z-index: 5;
            white-space: normal;
        }

        .info-icon:focus-visible::after,
        .info-icon:hover::after {
            opacity: 1;
            transform: translate(-50%, 4px);
        }

        .controls {
            display: inline-flex;
            align-items: center;
            gap: 0.75rem;
            flex-wrap: wrap;
        }

        .controls select,
        .controls button {
            background: rgba(15, 23, 42, 0.7);
            color: inherit;
            border: 1px solid rgba(148, 163, 184, 0.35);
            padding: 0.45rem 0.75rem;
            border-radius: 0.75rem;
            font-size: 0.95rem;
        }

        .controls button {
            background: rgba(56, 189, 248, 0.2);
            border-color: rgba(56, 189, 248, 0.4);
            cursor: pointer;
            transition: transform 0.2s ease, background 0.2s ease;
        }

        .controls button:hover,
        .controls button:focus-visible {
            background: rgba(56, 189, 248, 0.3);
            transform: translateY(-1px);
        }

        .controls button:active {
            transform: translateY(1px);
        }

        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1.25rem;
            margin-top: 1.25rem;
        }

        .stat {
            background: rgba(15, 23, 42, 0.6);
            border-radius: 1rem;
            padding: 1.25rem;
            border: 1px solid rgba(148, 163, 184, 0.2);
            display: grid;
            gap: 0.5rem;
        }

        .stat .label {
            font-size: 0.85rem;
            color: rgba(148, 163, 184, 0.9);
            display: inline-flex;
            gap: 0.35rem;
            align-items: center;
        }

        .stat .value {
            font-size: 1.4rem;
            font-weight: 600;
        }

        .table-card {
            display: grid;
            gap: 1rem;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        thead th {
            text-align: left;
            font-weight: 600;
            font-size: 0.85rem;
            color: rgba(148, 163, 184, 0.9);
            padding-bottom: 0.5rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.2);
        }

        tbody td {
            padding: 0.55rem 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.08);
        }

        tbody tr:last-child td {
            border-bottom: none;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            border-radius: 999px;
            font-size: 0.8rem;
            padding: 0.2rem 0.65rem;
        }

        .badge.success {
            background: rgba(34, 197, 94, 0.18);
            border: 1px solid rgba(34, 197, 94, 0.35);
            color: #bbf7d0;
        }

        .badge.warning {
            background: rgba(249, 115, 22, 0.18);
            border: 1px solid rgba(249, 115, 22, 0.35);
            color: #fed7aa;
        }

        .badge.danger {
            background: rgba(248, 113, 113, 0.18);
            border: 1px solid rgba(248, 113, 113, 0.35);
            color: #fecaca;
        }

        .risk-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
        }

        .risk-card {
            background: rgba(15, 23, 42, 0.6);
            border-radius: 1rem;
            padding: 1rem;
            border: 1px solid rgba(248, 113, 113, 0.2);
        }

        .risk-card h3 {
            margin: 0 0 0.35rem;
            font-size: 1rem;
        }

        .risk-card p {
            margin: 0;
            font-size: 0.85rem;
            color: rgba(248, 250, 252, 0.85);
        }

        .cost-grid {
            display: grid;
            gap: 1rem;
        }

        .cost-card {
            background: rgba(15, 23, 42, 0.6);
            border-radius: 1rem;
            padding: 1rem;
            border: 1px solid rgba(56, 189, 248, 0.2);
        }

        .cost-card h3 {
            margin: 0 0 0.5rem;
            font-size: 1rem;
        }

        .cost-card p {
            margin: 0;
            font-size: 0.85rem;
        }

        footer {
            text-align: center;
            padding: 2rem 1.5rem 3rem;
            color: rgba(148, 163, 184, 0.7);
            font-size: 0.8rem;
        }

        footer a {
            color: inherit;
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
<body data-version=\"__PERONA_VERSION__\">
    <header>
        <button class=\"wrangler-toggle\" id=\"wrangler-menu-toggle\" type=\"button\" aria-haspopup=\"true\" aria-expanded=\"false\" aria-controls=\"wrangler-menu\">
            <span aria-hidden=\"true\">☰</span>
            <span class=\"sr-only\">Open Wrangler scripts menu</span>
        </button>
        <h1>Perona Operational Dashboard</h1>
        <p>A refreshed, responsive control surface for render telemetry, risk signals, and cost analytics backed by the Perona engine.</p>
    </header>
    <div class=\"wrangler-overlay\" id=\"wrangler-menu-overlay\" hidden>
        <div class=\"wrangler-menu\" id=\"wrangler-menu\" role=\"dialog\" aria-modal=\"true\" aria-labelledby=\"wrangler-menu-title\">
            <div class=\"wrangler-menu-header\">
                <h2 class=\"wrangler-menu-title\" id=\"wrangler-menu-title\">Wrangler scripts</h2>
                <button class=\"wrangler-close\" id=\"wrangler-menu-close\" type=\"button\" aria-label=\"Close Wrangler menu\">&times;</button>
            </div>
            <div class=\"wrangler-menu-body\">
                <p class=\"muted\" id=\"wrangler-menu-status\" aria-live=\"polite\">Loading scripts…</p>
                <ul class=\"wrangler-menu-list\" id=\"wrangler-menu-list\"></ul>
            </div>
        </div>
    </div>
    <main>
        <div class=\"grid\">
            <section class=\"card fade-in span-4\" id=\"wrangler-results-card\" aria-live=\"polite\">
                <div class=\"wrangler-results-header\">
                    <h2 class=\"heading-with-icon\">
                        Overview
                        <span class=\"info-icon\" tabindex=\"0\" aria-label=\"High-level snapshot of current render health and operations.\" data-tooltip=\"High-level snapshot of current render health and operations.\"></span>
                    </h2>
                    <p class=\"muted\" id=\"wrangler-results-status\">Select a script to run from the Wrangler menu.</p>
                </div>
                <div class=\"wrangler-results-body\" id=\"wrangler-results-body\"></div>
            </section>
            <section class=\"card fade-in span-12\">
                <div style=\"display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;\">
                    <div>
                        <h2 class=\"heading-with-icon\">
                            Overview
                            <span class=\"info-icon\" tabindex=\"0\" aria-label=\"High-level snapshot of current render health and operations.\" data-tooltip=\"High-level snapshot of current render health and operations.\"></span>
                        </h2>
                        <p class=\"muted\">Data window <span id=\"summary-generated\">—</span></p>
                    </div>
                    <div class=\"controls\">
                        <label for=\"auto-refresh-interval\">Auto refresh</label>
                        <select class=\"auto-refresh\" id=\"auto-refresh-interval\">
                            <option value=\"5000\">Every 5 seconds</option>
                            <option value=\"30000\">Every 30 seconds</option>
                            <option value=\"60000\" selected>Every 60 seconds</option>
                            <option value=\"300000\">Every 300 seconds</option>
                            <option value=\"0\">Auto refresh off</option>
                        </select>
                        <button class=\"refresh\" id=\"refresh-summary\" type=\"button\">Refresh data</button>
                    </div>
                </div>
                <p class=\"muted\" id=\"summary-status\" style=\"margin-top: 0.75rem;\">Gathering metrics…</p>
                <div class=\"stat-grid\">
                    <div class=\"stat\">
                        <span class=\"label\">
                            Render samples
                            <span class=\"info-icon\" tabindex=\"0\" aria-label=\"Number of telemetry samples captured in the current summary window.\" data-tooltip=\"Number of telemetry samples captured in the current summary window.\"></span>
                        </span>
                        <span class=\"value\" id=\"metrics-total\">—</span>
                    </div>
                    <div class=\"stat\">
                        <span class=\"label\">
                            Average FPS
                            <span class=\"info-icon\" tabindex=\"0\" aria-label=\"Average frames rendered per second across monitored nodes.\" data-tooltip=\"Average frames rendered per second across monitored nodes.\"></span>
                        </span>
                        <span class=\"value\" id=\"metrics-fps\">—</span>
                    </div>
                    <div class=\"stat\">
                        <span class=\"label\">
                            Frame time
                            <span class=\"info-icon\" tabindex=\"0\" aria-label=\"Average time taken to render a single frame.\" data-tooltip=\"Average time taken to render a single frame.\"></span>
                        </span>
                        <span class=\"value\" id=\"metrics-frame-time\">—</span>
                    </div>
                    <div class=\"stat\">
                        <span class=\"label\">
                            GPU utilisation
                            <span class=\"info-icon\" tabindex=\"0\" aria-label=\"Average proportion of GPU resources currently consumed by rendering.\" data-tooltip=\"Average proportion of GPU resources currently consumed by rendering.\"></span>
                        </span>
                        <span class=\"value\" id=\"metrics-gpu\">—</span>
                    </div>
                    <div class=\"stat\">
                        <span class=\"label\">
                            Errors / sample
                            <span class=\"info-icon\" tabindex=\"0\" aria-label=\"Average number of errors captured in each telemetry sample.\" data-tooltip=\"Average number of errors captured in each telemetry sample.\"></span>
                        </span>
                        <span class=\"value\" id=\"metrics-errors\">—</span>
                    </div>
                    <div class=\"stat\">
                        <span class=\"label\">
                            Critical risks
                            <span class=\"info-icon\" tabindex=\"0\" aria-label=\"Count of shots currently flagged with critical risk signals.\" data-tooltip=\"Count of shots currently flagged with critical risk signals.\"></span>
                        </span>
                        <span class=\"value\" id=\"risk-critical\">—</span>
                    </div>
                    <div class=\"stat\">
                        <span class=\"label\">
                            Net delta cost
                            <span class=\"info-icon\" tabindex=\"0\" aria-label=\"Difference between projected and actual spend across the monitored window.\" data-tooltip=\"Difference between projected and actual spend across the monitored window.\"></span>
                        </span>
                        <span class=\"value\" id=\"cost-delta\">—</span>
                    </div>
                </div>
                <div class=\"table-card\" style=\"margin-top: 1.75rem;\">
                    <div style=\"display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;\">
                        <div>
                            <h2 class=\"heading-with-icon\">Sequences</h2>
                            <p class=\"muted\">Performance of monitored sequences</p>
                        </div>
                        <button class=\"refresh\" id=\"download-summary\" type=\"button\">Download daily report</button>
                    </div>
                    <div class=\"table-container\">
                        <table>
                            <thead>
                                <tr>
                                    <th>Sequence</th>
                                    <th>Shots</th>
                                    <th>Avg FPS</th>
                                    <th>Frame time</th>
                                    <th>GPU utilisation</th>
                                    <th>Errors / sample</th>
                                </tr>
                            </thead>
                            <tbody id=\"sequence-rows\"></tbody>
                        </table>
                    </div>
                </div>
            </section>
            <section class=\"card fade-in span-8\">
                <div style=\"display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;\">
                    <div>
                        <h2 class=\"heading-with-icon\">Shot progress</h2>
                        <p class=\"muted\">Lifecycle and bottleneck overview</p>
                    </div>
                    <div class=\"controls\">
                        <label class=\"sr-only\" for=\"shots-sequence\">Filter by sequence</label>
                        <select id=\"shots-sequence\">
                            <option value=\"\">All sequences</option>
                        </select>
                        <label class=\"sr-only\" for=\"shots-artist\">Filter by artist</label>
                        <select id=\"shots-artist\">
                            <option value=\"\">All artists</option>
                        </select>
                    </div>
                </div>
                <div class=\"table-container\">
                    <table>
                        <thead>
                            <tr>
                                <th>Sequence</th>
                                <th>Shot</th>
                                <th>Stage</th>
                                <th>Started</th>
                                <th>Duration</th>
                                <th>Metrics</th>
                            </tr>
                        </thead>
                        <tbody id=\"shots-rows\"></tbody>
                    </table>
                </div>
            </section>
            <section class=\"card fade-in span-8\">
                <div style=\"display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;\">
                    <div>
                        <h2 class=\"heading-with-icon\">Risk outlook</h2>
                        <p class=\"muted\">Portfolio signals and risk factors</p>
                    </div>
                    <div class=\"badge warning\" id=\"risk-status\">Loading…</div>
                </div>
                <div class=\"risk-grid\" id=\"risk-cards\"></div>
            </section>
            <section class=\"card fade-in span-8\">
                <div style=\"display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;\">
                    <div>
                        <h2 class=\"heading-with-icon\">Cost intelligence</h2>
                        <p class=\"muted\">Spend tracking and optimisation insights</p>
                    </div>
                    <div class=\"badge success\" id=\"cost-status\">Stable</div>
                </div>
                <div class=\"cost-grid\">
                    <div class=\"cost-card\">
                        <h3>Cost per frame</h3>
                        <p class=\"muted\">Baseline <span id=\"cost-per-frame-baseline\">—</span></p>
                        <p>Current <strong id=\"cost-per-frame-current\">—</strong></p>
                        <p>Delta <span id=\"cost-per-frame-delta\">—</span></p>
                    </div>
                    <div class=\"cost-card\">
                        <h3>Top contributors</h3>
                        <ul id=\"cost-contributors\" style=\"margin: 0; padding-left: 1.25rem;\"></ul>
                    </div>
                </div>
            </section>
            <section class=\"card fade-in span-16\">
                <div style=\"display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;\">
                    <div>
                        <h2 class=\"heading-with-icon\">Live render feed</h2>
                        <p class=\"muted\">Real-time telemetry stream of render performance</p>
                    </div>
                    <button class=\"refresh\" id=\"stream-toggle\" type=\"button\" aria-pressed=\"false\">Pause stream</button>
                </div>
                <div class=\"table-container\">
                    <table>
                        <thead>
                            <tr>
                                <th>Status</th>
                                <th>Message</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><span class=\"badge warning\" id=\"stream-badge\">Connecting</span></td>
                                <td id=\"stream-status\">Attempting to open a WebSocket connection…</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div class=\"table-container\" style=\"margin-top: 1rem;\">
                    <table>
                        <thead>
                            <tr>
                                <th>Sequence</th>
                                <th>Shot</th>
                                <th>FPS</th>
                                <th>Frame time</th>
                                <th>Timestamp</th>
                            </tr>
                        </thead>
                        <tbody id=\"stream-rows\"></tbody>
                    </table>
                </div>
            </section>
        </div>
    </main>
    <footer>
        <p>Perona platform version <strong id=\"perona-version\">__PERONA_VERSION__</strong>. Built for VFX operations teams to deliver renders faster, safer, and more cost-effectively.</p>
    </footer>
    <script>
        const byId = (id) => document.getElementById(id);
        const summaryStatus = byId('summary-status');
        const summaryGenerated = byId('summary-generated');
        const metricsTotal = byId('metrics-total');
        const metricsFps = byId('metrics-fps');
        const metricsFrameTime = byId('metrics-frame-time');
        const metricsGpu = byId('metrics-gpu');
        const metricsErrors = byId('metrics-errors');
        const riskCritical = byId('risk-critical');
        const costDelta = byId('cost-delta');
        const sequenceRows = byId('sequence-rows');
        const shotsRows = byId('shots-rows');
        const riskCards = byId('risk-cards');
        const costPerFrameBaseline = byId('cost-per-frame-baseline');
        const costPerFrameCurrent = byId('cost-per-frame-current');
        const costPerFrameDelta = byId('cost-per-frame-delta');
        const costContributors = byId('cost-contributors');
        const downloadSummaryButton = byId('download-summary');
        const shotsSequence = byId('shots-sequence');
        const shotsArtist = byId('shots-artist');
        const wranglerToggle = byId('wrangler-menu-toggle');
        const wranglerOverlay = byId('wrangler-menu-overlay');
        const wranglerMenu = byId('wrangler-menu');
        const wranglerMenuStatus = byId('wrangler-menu-status');
        const wranglerMenuList = byId('wrangler-menu-list');
        const wranglerClose = byId('wrangler-menu-close');
        const wranglerResultsCard = byId('wrangler-results-card');
        const wranglerResultsStatus = byId('wrangler-results-status');
        const wranglerResultsBody = byId('wrangler-results-body');
        const peronaVersion = byId('perona-version');
        const autoRefreshInterval = byId('auto-refresh-interval');
        const refreshSummaryButton = byId('refresh-summary');
        const streamToggle = byId('stream-toggle');
        const streamBadge = byId('stream-badge');
        const streamStatus = byId('stream-status');
        const streamRows = byId('stream-rows');

        peronaVersion.textContent = document.body.dataset.version ?? 'unknown';

        const formatNumber = (value, options = {}) => {
            if (value === null || value === undefined || Number.isNaN(value)) {
                return '—';
            }
            return new Intl.NumberFormat(undefined, options).format(value);
        };

        const formatDateTime = (value) => {
            if (!value) {
                return '—';
            }
            try {
                const date = new Date(value);
                return date.toLocaleString();
            } catch (error) {
                return value;
            }
        };

        const renderSequences = (sequences = []) => {
            sequenceRows.innerHTML = '';
            const fragment = document.createDocumentFragment();
            sequences.forEach((sequence) => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${sequence.sequence ?? '—'}</td>
                    <td>${sequence.shots ?? '—'}</td>
                    <td>${formatNumber(sequence.avg_fps, { maximumFractionDigits: 1 })}</td>
                    <td>${formatNumber(sequence.avg_frame_time_ms, { maximumFractionDigits: 0 })}</td>
                    <td>${formatNumber(sequence.avg_gpu_utilisation, { maximumFractionDigits: 0 })}</td>
                    <td>${formatNumber(sequence.avg_error_count, { maximumFractionDigits: 1 })}</td>
                `;
                fragment.appendChild(row);
            });
            sequenceRows.appendChild(fragment);
        };

        const renderShots = (shots = []) => {
            shotsRows.innerHTML = '';
            const fragment = document.createDocumentFragment();
            shots.forEach((shot) => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${shot.sequence ?? '—'}</td>
                    <td>${shot.shot_id ?? '—'}</td>
                    <td>${shot.current_stage ?? '—'}</td>
                    <td>${formatDateTime(shot.stage_started_at)}</td>
                    <td>${shot.stage_duration ?? '—'}</td>
                    <td>${shot.stage_metrics ?? '—'}</td>
                `;
                fragment.appendChild(row);
            });
            shotsRows.appendChild(fragment);
        };

        const renderRiskCards = (risks = []) => {
            riskCards.innerHTML = '';
            const fragment = document.createDocumentFragment();
            risks.forEach((risk) => {
                const card = document.createElement('div');
                card.className = 'risk-card';
                card.innerHTML = `
                    <h3>${risk.sequence ?? '—'} ${risk.shot_id ?? ''}</h3>
                    <p>Risk score: <strong>${formatNumber(risk.risk_score, { maximumFractionDigits: 0 })}</strong></p>
                    <p>${risk.drivers ?? 'No drivers provided'}</p>
                `;
                fragment.appendChild(card);
            });
            riskCards.appendChild(fragment);
        };

        const renderCosts = (costs = {}) => {
            costPerFrameBaseline.textContent = costs.baseline_cost_per_frame ?? '—';
            costPerFrameCurrent.textContent = costs.current_cost_per_frame ?? '—';
            costPerFrameDelta.textContent = costs.delta_cost_per_frame ?? '—';
            costContributors.innerHTML = '';
            if (!Array.isArray(costs.top_contributors) || costs.top_contributors.length === 0) {
                const item = document.createElement('li');
                item.textContent = 'No significant contributors';
                costContributors.appendChild(item);
                return;
            }
            costs.top_contributors.forEach((contributor) => {
                const item = document.createElement('li');
                item.textContent = `${contributor.factor ?? 'Unknown'} — ${contributor.delta_cost ?? '—'}`;
                costContributors.appendChild(item);
            });
        };

        const populateFilters = async () => {
            try {
                const response = await fetch('./shots/sequences');
                if (!response.ok) {
                    throw new Error('Failed to fetch sequences');
                }
                const sequences = await response.json();
                const uniqueSequences = new Set();
                const uniqueArtists = new Set();
                sequences.forEach((sequence) => {
                    uniqueSequences.add(sequence.name);
                    (sequence.shots ?? []).forEach((shot) => {
                        if (shot?.artist) {
                            uniqueArtists.add(shot.artist);
                        }
                    });
                });

                shotsSequence.innerHTML = '<option value="">All sequences</option>';
                uniqueSequences.forEach((sequence) => {
                    const option = document.createElement('option');
                    option.value = sequence ?? '';
                    option.textContent = sequence ?? 'Unknown';
                    shotsSequence.appendChild(option);
                });

                shotsArtist.innerHTML = '<option value="">All artists</option>';
                uniqueArtists.forEach((artist) => {
                    const option = document.createElement('option');
                    option.value = artist ?? '';
                    option.textContent = artist ?? 'Unknown';
                    shotsArtist.appendChild(option);
                });
            } catch (error) {
                console.error(error);
            }
        };

        const fetchSummary = async () => {
            summaryStatus.textContent = 'Refreshing data…';
            try {
                const params = new URLSearchParams();
                if (shotsSequence.value) {
                    params.set('sequence', shotsSequence.value);
                }
                if (shotsArtist.value) {
                    params.set('artist', shotsArtist.value);
                }
                const response = await fetch(`./dashboard/summary?${params.toString()}`);
                if (!response.ok) {
                    throw new Error('Failed to load summary');
                }
                const summary = await response.json();
                summaryGenerated.textContent = summary.generated_at ?? 'Unknown';
                metricsTotal.textContent = formatNumber(summary.metrics?.total_samples);
                metricsFps.textContent = formatNumber(summary.metrics?.average_fps, { maximumFractionDigits: 1 });
                metricsFrameTime.textContent = formatNumber(summary.metrics?.average_frame_time_ms, { maximumFractionDigits: 0 });
                metricsGpu.textContent = formatNumber(summary.metrics?.average_gpu_utilisation, { maximumFractionDigits: 0 });
                metricsErrors.textContent = formatNumber(summary.metrics?.average_error_count, { maximumFractionDigits: 1 });
                riskCritical.textContent = formatNumber(summary.risk?.critical_count, { maximumFractionDigits: 0 });
                costDelta.textContent = summary.costs?.delta_total_cost ?? '—';
                renderSequences(summary.metrics?.sequences ?? []);
                renderShots(summary.shots?.notable_active ?? []);
                renderRiskCards(summary.risk?.top_risks ?? []);
                renderCosts(summary.costs ?? {});
                summaryStatus.textContent = 'Data refreshed';
            } catch (error) {
                console.error(error);
                summaryStatus.textContent = 'Unable to refresh data';
            }
        };

        const scheduleAutoRefresh = () => {
            const interval = Number.parseInt(autoRefreshInterval.value, 10);
            if (!Number.isFinite(interval) || interval <= 0) {
                return null;
            }
            return window.setInterval(fetchSummary, interval);
        };

        let autoRefreshTimer = scheduleAutoRefresh();

        autoRefreshInterval.addEventListener('change', () => {
            if (autoRefreshTimer) {
                window.clearInterval(autoRefreshTimer);
            }
            autoRefreshTimer = scheduleAutoRefresh();
        });

        refreshSummaryButton.addEventListener('click', () => {
            fetchSummary().catch(() => {});
        });

        const wrangler = {
            isOpen: false,
            scripts: [],
        };

        const renderWranglerScripts = () => {
            wranglerMenuList.innerHTML = '';
            if (!Array.isArray(wrangler.scripts) || wrangler.scripts.length === 0) {
                const item = document.createElement('li');
                item.className = 'muted';
                item.textContent = 'No Wrangler scripts registered.';
                wranglerMenuList.appendChild(item);
                return;
            }
            wrangler.scripts.forEach((script) => {
                const item = document.createElement('li');
                item.className = 'wrangler-menu-item';
                item.innerHTML = `
                    <div>
                        <h3>${script.name ?? script.script_id}</h3>
                        <p class='muted'>${script.description ?? 'No description provided.'}</p>
                    </div>
                    <button type="button">Run script</button>
                `;
                const button = item.querySelector('button');
                button.addEventListener('click', async () => {
                    wranglerResultsStatus.textContent = `Running ${script.name ?? script.script_id}…`;
                    wranglerResultsBody.innerHTML = '';
                    try {
                        const response = await fetch(`./wrangler/scripts/${script.script_id}`, {
                            method: 'POST',
                        });
                        const result = await response.json();
                        wranglerResultsStatus.textContent = result.status ?? 'Completed';
                        wranglerResultsBody.textContent = result.message ?? JSON.stringify(result, null, 2);
                    } catch (error) {
                        console.error(error);
                        wranglerResultsStatus.textContent = 'Failed to execute script';
                    }
                });
                wranglerMenuList.appendChild(item);
            });
        };

        const fetchWranglerScripts = async () => {
            wranglerMenuStatus.textContent = 'Loading scripts…';
            try {
                const response = await fetch('./wrangler/scripts');
                if (!response.ok) {
                    throw new Error('Failed to fetch scripts');
                }
                wrangler.scripts = await response.json();
                renderWranglerScripts();
                wranglerMenuStatus.textContent = `${wrangler.scripts.length} scripts available`;
            } catch (error) {
                console.error(error);
                wranglerMenuStatus.textContent = 'Unable to load scripts';
            }
        };

        const openWranglerMenu = () => {
            wrangler.isOpen = true;
            wranglerOverlay.hidden = false;
            wranglerToggle.setAttribute('aria-expanded', 'true');
            fetchWranglerScripts().catch(() => {});
            const focusable = wranglerMenu.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
            if (focusable) {
                focusable.focus();
            }
        };

        const closeWranglerMenu = () => {
            wrangler.isOpen = false;
            wranglerOverlay.hidden = true;
            wranglerToggle.setAttribute('aria-expanded', 'false');
            wranglerToggle.focus();
        };

        wranglerToggle.addEventListener('click', () => {
            if (wrangler.isOpen) {
                closeWranglerMenu();
            } else {
                openWranglerMenu();
            }
        });

        wranglerClose.addEventListener('click', () => {
            closeWranglerMenu();
        });

        wranglerOverlay.addEventListener('click', (event) => {
            if (event.target === wranglerOverlay) {
                closeWranglerMenu();
            }
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && wrangler.isOpen) {
                closeWranglerMenu();
            }
        });

        const downloadDailyReport = async () => {
            try {
                const response = await fetch('./reports/daily');
                if (!response.ok) {
                    throw new Error('Failed to download report');
                }
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                const disposition = response.headers.get('content-disposition');
                const match = disposition && disposition.match(/filename="([^"]+)"/i);
                link.download = match ? match[1] : 'perona_daily_summary.csv';
                document.body.appendChild(link);
                link.click();
                link.remove();
                window.URL.revokeObjectURL(url);
            } catch (error) {
                console.error(error);
            }
        };

        downloadSummaryButton.addEventListener('click', () => {
            downloadDailyReport().catch(() => {});
        });

        const loadShots = async () => {
            try {
                const params = new URLSearchParams();
                if (shotsSequence.value) {
                    params.set('sequence', shotsSequence.value);
                }
                if (shotsArtist.value) {
                    params.set('artist', shotsArtist.value);
                }
                const response = await fetch(`./shots?${params.toString()}`);
                if (!response.ok) {
                    throw new Error('Failed to load shots');
                }
                const data = await response.json();
                renderShots(data.active_shots ?? []);
            } catch (error) {
                console.error(error);
            }
        };

        shotsSequence.addEventListener('change', () => {
            fetchSummary().catch(() => {});
            loadShots().catch(() => {});
        });

        shotsArtist.addEventListener('change', () => {
            fetchSummary().catch(() => {});
            loadShots().catch(() => {});
        });

        const startMetricsStream = () => {
            if (!window.WebSocket) {
                streamBadge.textContent = 'Unsupported';
                streamStatus.textContent = 'WebSocket not supported by your browser.';
                streamToggle.disabled = true;
                return;
            }

            const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const url = `${protocol}://${window.location.host}/ws/metrics`;
            let reconnectTimer;
            let socket;
            let isPaused = false;
            let isConnected = false;

            const setStatus = (badgeText, statusText) => {
                streamBadge.textContent = badgeText;
                streamStatus.textContent = statusText;
            };

            const updateToggleText = () => {
                if (!streamToggle) {
                    return;
                }
                streamToggle.textContent = isPaused ? 'Resume stream' : 'Pause stream';
                streamToggle.setAttribute('aria-pressed', isPaused ? 'true' : 'false');
            };

            if (streamToggle) {
                updateToggleText();
                streamToggle.addEventListener('click', () => {
                    isPaused = !isPaused;
                    updateToggleText();
                    if (isPaused) {
                        const pausedMessage = isConnected
                            ? 'Live stream paused.'
                            : 'Live stream paused. Waiting for connection…';
                        setStatus('Paused', pausedMessage);
                    } else if (isConnected) {
                        setStatus('Live', 'Streaming live render metrics.');
                    } else {
                        setStatus('Connecting', 'Attempting to open a WebSocket connection…');
                    }
                });
            }

            const connect = () => {
                if (streamToggle) {
                    streamToggle.disabled = false;
                }
                socket = new WebSocket(url);
                isConnected = false;
                if (!isPaused) {
                    setStatus('Connecting', 'Attempting to open a WebSocket connection…');
                } else {
                    setStatus('Paused', 'Live stream paused. Waiting for connection…');
                }

                socket.addEventListener('open', () => {
                    isConnected = true;
                    if (streamToggle) {
                        streamToggle.disabled = false;
                    }
                    if (isPaused) {
                        setStatus('Paused', 'Live stream paused.');
                    } else {
                        setStatus('Live', 'Streaming live render metrics.');
                    }
                });

                socket.addEventListener('message', (event) => {
                    if (isPaused) {
                        return;
                    }
                    try {
                        const sample = JSON.parse(event.data ?? '{}');
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${sample.sequence ?? '—'}</td>
                            <td>${sample.shot_id ?? '—'}</td>
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
                        console.error('Failed to render metrics sample', error);
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

                socket.addEventListener('close', () => {
                    isConnected = false;
                    const pausedMessage = isPaused
                        ? 'Live stream paused. Reconnecting will resume updates…'
                        : 'Live stream disconnected. Reconnecting shortly…';
                    setStatus('Paused', pausedMessage);
                    scheduleReconnect();
                });

                socket.addEventListener('error', () => {
                    isConnected = false;
                    setStatus('Offline', 'Unable to connect to the render feed.');
                    if (streamToggle) {
                        streamToggle.disabled = true;
                    }
                    socket.close();
                });
            };

            connect();
        };

        fetchSummary().catch((error) => {
            console.error(error);
        });
        populateFilters().catch(() => {});
        loadShots().catch(() => {});
        startMetricsStream();
    </script>
</body>
</html>
"""
    return template.replace("__PERONA_VERSION__", PERONA_VERSION)


__all__ = ["dashboard_index_html"]
