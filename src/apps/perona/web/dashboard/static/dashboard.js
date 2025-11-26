const byId = (id) => document.getElementById(id);
const summaryStatus = byId('summary-status');
const summaryGenerated = byId('summary-generated');
const metricsTotal = byId('metrics-total');
const metricsFps = byId('metrics-fps');
const metricsFrameTime = byId('metrics-frame-time');
const metricsGpu = byId('metrics-gpu');
const metricsErrors = byId('metrics-errors');
const riskCritical = byId('risk-critical');
const riskStatus = byId('risk-status');
const riskSort = byId('risk-sort');
const riskFilter = byId('risk-filter');
const costDelta = byId('cost-delta');
const sequenceRows = byId('sequence-rows');
const shotsRows = byId('shots-rows');
const riskCards = byId('risk-cards');
const riskLegend = byId('risk-legend');
const costPerFrameBaseline = byId('cost-per-frame-baseline');
const costPerFrameCurrent = byId('cost-per-frame-current');
const costPerFrameDelta = byId('cost-per-frame-delta');
const costContributors = byId('cost-contributors');
const costTrendChartCanvas = byId('cost-trend-chart');
const pnlBreakdownChartCanvas = byId('pnl-breakdown-chart');
const riskHeatmapChartCanvas = byId('risk-heatmap-chart');
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
const timeRange = byId('time-range');
const metricsTrendChartCanvas = byId('metrics-trend-chart');
const livePerformanceChartCanvas = byId('live-performance-chart');
const liveErrorChartCanvas = byId('live-error-chart');
const liveFpsValue = byId('live-fps-value');
const liveGpuValue = byId('live-gpu-value');
const liveErrorsValue = byId('live-errors-value');
const optimizationForm = byId('optimization-form');
const optimizationRunButton = byId('optimization-run');
const optimizationClearButton = byId('optimization-clear');
const optimizationScenarioTable = byId('optimization-scenarios');
const optimizationQueueCount = byId('optimization-queue-count');
const optimizationStatus = byId('optimization-status');
const optimizationResults = byId('optimization-results');
const optimizationResultsChartCanvas = byId('optimization-results-chart');
const optimizationScenarioName = byId('optimization-scenario-name');
const optimizationGpuCount = byId('optimization-gpu-count');
const optimizationGpuRate = byId('optimization-gpu-rate');
const optimizationFrameScale = byId('optimization-frame-scale');
const optimizationResolutionScale = byId('optimization-resolution-scale');
const optimizationSamplingScale = byId('optimization-sampling-scale');
const optimizationNotes = byId('optimization-notes');

peronaVersion.textContent = document.body.dataset.version ?? 'unknown';

const formatNumber = (value, options = {}) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return '—';
    }
    return new Intl.NumberFormat(undefined, options).format(value);
};

const formatCurrency = (value, currency) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return '—';
    }
    return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: currency || 'USD',
        maximumFractionDigits: 2,
    }).format(value);
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

const TIME_RANGE_WINDOWS = {
    '1h': { durationMs: 60 * 60 * 1000, label: 'Last hour' },
    '24h': { durationMs: 24 * 60 * 60 * 1000, label: 'Last 24 hours' },
    '7d': { durationMs: 7 * 24 * 60 * 60 * 1000, label: 'Last 7 days' },
};

const getSelectedTimeRange = () => {
    const selection = timeRange?.value || '24h';
    const config = TIME_RANGE_WINDOWS[selection] ?? TIME_RANGE_WINDOWS['24h'];
    const to = new Date();
    const from = new Date(to.getTime() - config.durationMs);
    return { from: from.toISOString(), to: to.toISOString(), label: config.label };
};

const applyTimeRangeParams = (params) => {
    const range = getSelectedTimeRange();
    if (range.from) {
        params.set('from', range.from);
    }
    if (range.to) {
        params.set('to', range.to);
    }
    return range;
};

const RISK_THRESHOLDS = {
    critical: 85,
    high: 65,
    medium: 40,
    low: 20,
};

const getRiskSeverity = (riskScore) => {
    if (!Number.isFinite(riskScore)) {
        return 'stable';
    }
    if (riskScore >= RISK_THRESHOLDS.critical) {
        return 'critical';
    }
    if (riskScore >= RISK_THRESHOLDS.high) {
        return 'high';
    }
    if (riskScore >= RISK_THRESHOLDS.medium) {
        return 'medium';
    }
    if (riskScore >= RISK_THRESHOLDS.low) {
        return 'low';
    }
    return 'stable';
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

const RISK_SEVERITY_META = {
    critical: { label: 'Critical', badge: 'danger', description: 'Immediate intervention required' },
    high: { label: 'High', badge: 'warning', description: 'Investigate promptly' },
    medium: { label: 'Medium', badge: 'warning', description: 'Monitor and mitigate' },
    low: { label: 'Low', badge: 'success', description: 'Within acceptable bounds' },
    stable: { label: 'Stable', badge: 'success', description: 'Healthy performance' },
};

const renderRiskCards = (risks = []) => {
    if (!riskCards) {
        return;
    }
    riskCards.innerHTML = '';

    if (!Array.isArray(risks) || risks.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'muted';
        empty.textContent = 'No risk indicators available.';
        riskCards.appendChild(empty);
        return;
    }

    const fragment = document.createDocumentFragment();
    risks.forEach((risk) => {
        const severity = getRiskSeverity(risk?.risk_score);
        const severityMeta = RISK_SEVERITY_META[severity] ?? RISK_SEVERITY_META.stable;
        const card = document.createElement('div');
        card.className = `risk-card severity-${severity}`;
        card.setAttribute('aria-label', `${severityMeta.label} risk for ${risk.sequence ?? 'sequence'} ${risk.shot_id ?? ''}`);

        const drivers = Array.isArray(risk.drivers)
            ? risk.drivers.join(', ')
            : risk.drivers ?? 'No drivers provided';

        const errorRate = formatNumber(risk.error_rate, { maximumFractionDigits: 1 });
        const cacheStability = formatNumber(risk.cache_stability, { maximumFractionDigits: 1 });
        const renderTime = formatNumber(risk.render_time_ms, { maximumFractionDigits: 0 });

        card.innerHTML = `
            <h3>${risk.sequence ?? '—'} ${risk.shot_id ?? ''}</h3>
            <p class="risk-score">
                <span class="badge ${severityMeta.badge}">${severityMeta.label}</span>
                Risk score: <strong>${formatNumber(risk.risk_score, { maximumFractionDigits: 0 })}</strong>
            </p>
            <p>
                Render time: ${renderTime} ms · Error rate: ${errorRate}% · Cache stability: ${cacheStability}%
            </p>
            <p>${drivers}</p>
        `;
        fragment.appendChild(card);
    });
    riskCards.appendChild(fragment);
};

const renderRiskLegend = (risks = []) => {
    if (!riskLegend) {
        return;
    }
    riskLegend.innerHTML = '';
    const severityOrder = ['critical', 'high', 'medium', 'low', 'stable'];
    const fragment = document.createDocumentFragment();

    severityOrder.forEach((level) => {
        const meta = RISK_SEVERITY_META[level];
        const count = risks.filter((risk) => getRiskSeverity(risk?.risk_score) === level).length;
        const item = document.createElement('div');
        item.className = 'risk-legend__item';
        item.innerHTML = `
            <span class="risk-legend__swatch severity-${level}" aria-hidden="true"></span>
            <span>${meta.label}</span>
            <span class="muted">(${count})</span>
        `;
        item.setAttribute('aria-label', `${meta.label} severity: ${count} shots`);
        fragment.appendChild(item);
    });

    riskLegend.appendChild(fragment);
};

const updateRiskStatus = (risks = []) => {
    if (!riskStatus) {
        return;
    }
    if (!Array.isArray(risks) || risks.length === 0) {
        riskStatus.className = 'badge success';
        riskStatus.textContent = 'No risk indicators';
        return;
    }
    const highest = risks.reduce((max, risk) => Math.max(max, Number(risk?.risk_score) || 0), 0);
    const severity = getRiskSeverity(highest);
    const meta = RISK_SEVERITY_META[severity];
    const badgeClass = severity === 'critical' ? 'danger' : severity === 'high' ? 'warning' : 'success';
    riskStatus.className = `badge ${badgeClass}`;
    riskStatus.textContent = `${meta.label} risk window`;
};

const renderRiskHeatmapChart = (risks = []) => {
    if (!riskHeatmapChartCanvas || typeof Chart === 'undefined') {
        return;
    }

    const grouped = new Map();
    risks.forEach((risk) => {
        const key = risk.sequence ?? 'Unknown sequence';
        const existing = grouped.get(key) ?? { total: 0, count: 0, critical: 0 };
        const riskScore = Number(risk.risk_score) || 0;
        grouped.set(key, {
            total: existing.total + riskScore,
            count: existing.count + 1,
            critical: existing.critical + (getRiskSeverity(risk.risk_score) === 'critical' ? 1 : 0),
        });
    });

    const labels = Array.from(grouped.keys());
    const averages = labels.map((label) => {
        const entry = grouped.get(label);
        return entry && entry.count ? entry.total / entry.count : 0;
    });
    const criticalCounts = labels.map((label) => grouped.get(label)?.critical ?? 0);

    if (labels.length === 0) {
        labels.push('No data');
        averages.push(0);
        criticalCounts.push(0);
    }

    if (riskHeatmapChart) {
        riskHeatmapChart.destroy();
    }

    riskHeatmapChart = new Chart(riskHeatmapChartCanvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Average risk score',
                    data: averages,
                    backgroundColor: 'rgba(248, 113, 113, 0.6)',
                    borderColor: 'rgba(248, 113, 113, 0.9)',
                    borderWidth: 1,
                },
                {
                    label: 'Critical shots',
                    data: criticalCounts,
                    backgroundColor: 'rgba(249, 115, 22, 0.5)',
                    borderColor: 'rgba(249, 115, 22, 0.85)',
                    borderWidth: 1,
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'Average risk score' },
                },
                y1: {
                    beginAtZero: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: 'Critical items' },
                },
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            if (context.dataset.yAxisID === 'y1') {
                                return `${context.parsed.y} critical shots`;
                            }
                            return `Average risk: ${formatNumber(context.parsed.y, { maximumFractionDigits: 1 })}`;
                        },
                    },
                },
                legend: {
                    labels: {
                        filter: (item, data) => data.datasets[item.datasetIndex].data.some((value) => value !== 0),
                    },
                },
            },
        },
    });
};

const filterRiskIndicators = (risks = []) => {
    const filterValue = riskFilter?.value ?? 'all';
    const allowed = {
        all: ['critical', 'high', 'medium', 'low', 'stable'],
        critical: ['critical'],
        high: ['critical', 'high'],
        medium: ['critical', 'high', 'medium'],
    };
    const allowedSeverities = allowed[filterValue] ?? allowed.all;
    return risks.filter((risk) => allowedSeverities.includes(getRiskSeverity(risk?.risk_score)));
};

const sortRiskIndicators = (risks = []) => {
    const sort = riskSort?.value ?? 'desc';
    const sorted = [...risks];
    if (sort === 'asc') {
        sorted.sort((a, b) => (Number(a?.risk_score) || 0) - (Number(b?.risk_score) || 0));
        return sorted;
    }
    if (sort === 'sequence') {
        sorted.sort((a, b) => {
            const sequenceComparison = (a.sequence ?? '').localeCompare(b.sequence ?? '');
            if (sequenceComparison !== 0) {
                return sequenceComparison;
            }
            return (Number(b?.risk_score) || 0) - (Number(a?.risk_score) || 0);
        });
        return sorted;
    }
    if (sort === 'shot') {
        sorted.sort((a, b) => (a.shot_id ?? '').localeCompare(b.shot_id ?? ''));
        return sorted;
    }
    sorted.sort((a, b) => (Number(b?.risk_score) || 0) - (Number(a?.risk_score) || 0));
    return sorted;
};

const applyRiskFilters = () => {
    const filtered = sortRiskIndicators(filterRiskIndicators(riskHeatmapData));
    renderRiskCards(filtered);
    renderRiskLegend(filtered);
    renderRiskHeatmapChart(filtered);
    updateRiskStatus(filtered);
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

let costTrendChart;
let pnlBreakdownChart;
let riskHeatmapChart;
let metricsTrendChart;
let riskHeatmapData = [];
let livePerformanceChart;
let liveErrorChart;
let optimizationResultsChart;

const optimizationState = {
    scenarios: [],
    baseline: null,
    currency: 'USD',
};

const getScaleLabel = (value) => {
    const numeric = Number.isFinite(value) ? value : 1;
    return `${formatNumber(numeric * 100, { maximumFractionDigits: 0 })}% of baseline`;
};

const setOptimizationBadge = (message, tone = '') => {
    if (!optimizationStatus) {
        return;
    }
    optimizationStatus.textContent = message;
    optimizationStatus.className = tone ? `badge ${tone}` : 'badge';
};

const resetOptimizationForm = () => {
    if (!optimizationForm) {
        return;
    }
    optimizationForm.reset();
    if (optimizationFrameScale) {
        optimizationFrameScale.value = '1';
    }
    if (optimizationResolutionScale) {
        optimizationResolutionScale.value = '1';
    }
    if (optimizationSamplingScale) {
        optimizationSamplingScale.value = '1';
    }
};

const renderOptimizationQueue = () => {
    if (!optimizationScenarioTable) {
        return;
    }

    optimizationScenarioTable.innerHTML = '';
    const configured = optimizationState.scenarios.length;
    if (optimizationQueueCount) {
        optimizationQueueCount.textContent = `${configured} configured`;
    }

    if (configured === 0) {
        const emptyRow = document.createElement('tr');
        emptyRow.innerHTML = '<td colspan="8" class="muted">No scenarios queued.</td>';
        optimizationScenarioTable.appendChild(emptyRow);
        return;
    }

    optimizationState.scenarios.forEach((scenario, index) => {
        const row = document.createElement('tr');
        const gpuRate = Number.isFinite(scenario.gpu_hourly_rate)
            ? formatCurrency(scenario.gpu_hourly_rate, optimizationState.currency)
            : '—';
        row.innerHTML = `
            <td>${scenario.name}</td>
            <td>${scenario.gpu_count ?? '—'}</td>
            <td>${gpuRate}</td>
            <td>${getScaleLabel(scenario.frame_time_scale)}</td>
            <td>${getScaleLabel(scenario.resolution_scale)}</td>
            <td>${getScaleLabel(scenario.sampling_scale)}</td>
            <td>${scenario.notes ?? '—'}</td>
            <td><button class="link-button" type="button" data-index="${index}">Remove</button></td>
        `;
        const removeButton = row.querySelector('button');
        removeButton.addEventListener('click', () => {
            optimizationState.scenarios.splice(index, 1);
            renderOptimizationQueue();
        });
        optimizationScenarioTable.appendChild(row);
    });
};

const parseOptimizationScenario = () => {
    const name = (optimizationScenarioName?.value || '').trim() || `Scenario ${optimizationState.scenarios.length + 1}`;
    const frameTimeScale = Number.parseFloat(optimizationFrameScale?.value ?? '1');
    const resolutionScale = Number.parseFloat(optimizationResolutionScale?.value ?? '1');
    const samplingScale = Number.parseFloat(optimizationSamplingScale?.value ?? '1');
    const gpuCount = Number.parseInt(optimizationGpuCount?.value ?? '', 10);
    const gpuHourlyRate = Number.parseFloat(optimizationGpuRate?.value ?? '');
    const scenario = {
        name,
        frame_time_scale: Number.isFinite(frameTimeScale) ? frameTimeScale : 1,
        resolution_scale: Number.isFinite(resolutionScale) ? resolutionScale : 1,
        sampling_scale: Number.isFinite(samplingScale) ? samplingScale : 1,
    };

    if (Number.isFinite(gpuCount)) {
        scenario.gpu_count = gpuCount;
    }
    if (Number.isFinite(gpuHourlyRate)) {
        scenario.gpu_hourly_rate = gpuHourlyRate;
    }
    const notes = (optimizationNotes?.value || '').trim();
    if (notes) {
        scenario.notes = notes;
    }
    return scenario;
};

const renderOptimizationResultsChart = (baseline, scenarios = []) => {
    if (!optimizationResultsChartCanvas || typeof Chart === 'undefined') {
        return;
    }

    const labels = ['Baseline', ...scenarios.map((scenario) => scenario.name)];
    const totalCosts = [baseline?.total_cost ?? 0, ...scenarios.map((scenario) => scenario.total_cost ?? 0)];
    const savings = [0, ...scenarios.map((scenario) => (baseline ? baseline.total_cost - scenario.total_cost : 0))];

    const savingsColors = savings.map((value) => (value >= 0 ? 'rgba(16, 185, 129, 0.7)' : 'rgba(248, 113, 113, 0.7)'));

    if (optimizationResultsChart) {
        optimizationResultsChart.destroy();
    }

    optimizationResultsChart = new Chart(optimizationResultsChartCanvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Total cost',
                    data: totalCosts,
                    backgroundColor: 'rgba(59, 130, 246, 0.6)',
                    borderColor: 'rgba(59, 130, 246, 0.9)',
                    borderWidth: 1,
                },
                {
                    label: 'Savings vs. baseline',
                    data: savings,
                    backgroundColor: savingsColors,
                    borderColor: savingsColors,
                    borderWidth: 1,
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: baseline?.currency ? `Total cost (${baseline.currency})` : 'Total cost' },
                },
                y1: {
                    beginAtZero: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: 'Savings (+) / Overruns (–)' },
                },
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const value = context.parsed.y;
                            if (context.dataset.label === 'Total cost') {
                                return formatCurrency(value, baseline?.currency ?? 'USD');
                            }
                            const deltaLabel = value >= 0 ? 'Savings' : 'Overrun';
                            return `${deltaLabel}: ${formatCurrency(value, baseline?.currency ?? 'USD')}`;
                        },
                    },
                },
            },
        },
    });
};

const renderDriverChanges = (baseline, scenario) => {
    const drivers = [
        {
            label: 'Cost per frame',
            baseline: baseline?.cost_per_frame,
            scenario: scenario.cost_per_frame,
            formatter: (value) => formatCurrency(value, baseline?.currency ?? 'USD'),
        },
        {
            label: 'GPU hours',
            baseline: baseline?.gpu_hours,
            scenario: scenario.gpu_hours,
            formatter: (value) => formatNumber(value, { maximumFractionDigits: 1 }),
        },
        {
            label: 'Render hours',
            baseline: baseline?.render_hours,
            scenario: scenario.render_hours,
            formatter: (value) => formatNumber(value, { maximumFractionDigits: 1 }),
        },
    ];

    const list = document.createElement('ul');
    list.style.paddingLeft = '1.25rem';
    drivers.forEach((driver) => {
        const delta = (driver.scenario ?? 0) - (driver.baseline ?? 0);
        const direction = delta === 0 ? 'No change' : delta > 0 ? 'Increase' : 'Decrease';
        const item = document.createElement('li');
        item.innerHTML = `
            <strong>${driver.label}</strong>: ${driver.formatter(driver.scenario ?? 0)}
            <span class="muted">(${direction} ${delta === 0 ? '' : driver.formatter(delta)})</span>
        `;
        list.appendChild(item);
    });
    return list;
};

const renderOptimizationResultsSummary = (baseline, scenarios = []) => {
    if (!optimizationResults) {
        return;
    }

    optimizationResults.innerHTML = '';
    if (!baseline) {
        optimizationResults.innerHTML = '<p class="muted">Run a backtest to see results.</p>';
        return;
    }

    if (!Array.isArray(scenarios) || scenarios.length === 0) {
        optimizationResults.innerHTML = '<p class="muted">No scenarios returned.</p>';
        return;
    }

    const fragment = document.createDocumentFragment();
    scenarios.forEach((scenario) => {
        const card = document.createElement('div');
        card.className = 'card';
        card.style.padding = '1rem';
        const savings = Number.isFinite(scenario.savings_vs_baseline)
            ? scenario.savings_vs_baseline
            : (baseline.total_cost ?? 0) - (scenario.total_cost ?? 0);
        const savingsPercent = Number.isFinite(scenario.savings_percent)
            ? scenario.savings_percent
            : baseline.total_cost
              ? (savings / baseline.total_cost) * 100
              : 0;
        const savingsLabel = savings >= 0 ? 'Savings' : 'Overrun';
        const badgeTone = savings >= 0 ? 'success' : 'warning';
        card.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;">
                <div>
                    <h4 style="margin: 0;">${scenario.name}</h4>
                    <p class="muted" style="margin: 0;">${scenario.notes || 'No notes provided.'}</p>
                </div>
                <span class="badge ${badgeTone}">${savingsLabel}</span>
            </div>
            <div class="stat-grid" style="margin-top: 0.5rem;">
                <div class="stat">
                    <span class="label">Total cost</span>
                    <span class="value">${formatCurrency(scenario.total_cost, baseline.currency)}</span>
                </div>
                <div class="stat">
                    <span class="label">Savings vs. baseline</span>
                    <span class="value">${formatCurrency(savings, baseline.currency)}</span>
                </div>
                <div class="stat">
                    <span class="label">Savings %</span>
                    <span class="value">${formatNumber(savingsPercent, { maximumFractionDigits: 1 })}%</span>
                </div>
                <div class="stat">
                    <span class="label">GPU hours</span>
                    <span class="value">${formatNumber(scenario.gpu_hours, { maximumFractionDigits: 1 })}</span>
                </div>
            </div>
        `;

        const drivers = renderDriverChanges(baseline, scenario);
        drivers.style.marginTop = '0.5rem';
        card.appendChild(drivers);
        fragment.appendChild(card);
    });

    optimizationResults.appendChild(fragment);
};

const runOptimizationBacktest = async () => {
    if (!optimizationState.scenarios.length) {
        setOptimizationBadge('Add at least one scenario to run a backtest.', 'warning');
        return;
    }

    setOptimizationBadge('Running backtest…', 'warning');
    try {
        const payload = {
            scenarios: optimizationState.scenarios,
        };

        const response = await fetch('./analytics/optimization/backtest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            throw new Error('Failed to run optimisation backtest');
        }

        const data = await response.json();
        optimizationState.baseline = data.baseline ?? null;
        optimizationState.currency = data.baseline?.currency ?? optimizationState.currency;
        renderOptimizationResultsSummary(data.baseline, data.scenarios ?? []);
        renderOptimizationResultsChart(data.baseline, data.scenarios ?? []);
        setOptimizationBadge('Backtest updated', 'success');
    } catch (error) {
        console.error(error);
        setOptimizationBadge('Unable to run backtest', 'danger');
    }
};

const LIVE_SAMPLE_LIMIT = 180;

const getShortTimeLabel = (value) => {
    if (!value) {
        return '—';
    }
    try {
        const date = new Date(value);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (error) {
        return value;
    }
};

const updateLiveSummary = (sample = {}) => {
    if (liveFpsValue) {
        liveFpsValue.textContent = formatNumber(sample.fps, { maximumFractionDigits: 1 });
    }
    if (liveGpuValue) {
        liveGpuValue.textContent = formatNumber(sample.gpu_utilisation, { maximumFractionDigits: 0 });
    }
    if (liveErrorsValue) {
        liveErrorsValue.textContent = formatNumber(sample.error_count, { maximumFractionDigits: 1 });
    }
};

const renderLiveCharts = (samples = []) => {
    if (typeof Chart === 'undefined') {
        return;
    }

    const labels = samples.map((sample) => getShortTimeLabel(sample.timestamp));
    const fpsData = samples.map((sample) => Number(sample.fps) || 0);
    const frameTimeData = samples.map((sample) => Number(sample.frame_time_ms) || 0);
    const gpuData = samples.map((sample) => Number(sample.gpu_utilisation) || 0);
    const errorData = samples.map((sample) => Number(sample.error_count) || 0);

    if (livePerformanceChartCanvas) {
        if (!livePerformanceChart) {
            livePerformanceChart = new Chart(livePerformanceChartCanvas, {
                type: 'line',
                data: {
                    labels: labels.length ? labels : ['Waiting for data'],
                    datasets: [
                        {
                            label: 'FPS',
                            data: labels.length ? fpsData : [0],
                            borderColor: 'rgba(59, 130, 246, 0.85)',
                            backgroundColor: 'rgba(59, 130, 246, 0.15)',
                            tension: 0.25,
                            yAxisID: 'fps',
                        },
                        {
                            label: 'Frame time (ms)',
                            data: labels.length ? frameTimeData : [0],
                            borderColor: 'rgba(234, 88, 12, 0.85)',
                            backgroundColor: 'rgba(234, 88, 12, 0.2)',
                            tension: 0.25,
                            yAxisID: 'frameTime',
                        },
                        {
                            label: 'GPU utilisation (%)',
                            data: labels.length ? gpuData : [0],
                            borderColor: 'rgba(34, 197, 94, 0.9)',
                            backgroundColor: 'rgba(34, 197, 94, 0.2)',
                            tension: 0.25,
                            yAxisID: 'gpu',
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    stacked: false,
                    scales: {
                        fps: {
                            type: 'linear',
                            position: 'left',
                            title: { display: true, text: 'FPS' },
                            suggestedMin: 0,
                        },
                        frameTime: {
                            type: 'linear',
                            position: 'right',
                            grid: { drawOnChartArea: false },
                            title: { display: true, text: 'Frame time (ms)' },
                        },
                        gpu: {
                            type: 'linear',
                            position: 'right',
                            offset: true,
                            grid: { drawOnChartArea: false },
                            title: { display: true, text: 'GPU utilisation (%)' },
                            suggestedMin: 0,
                            suggestedMax: 100,
                        },
                    },
                    plugins: {
                        legend: { display: true },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    const value = context.parsed.y;
                                    if (context.dataset.label?.includes('Frame time')) {
                                        return `Frame time: ${formatNumber(value, { maximumFractionDigits: 1 })} ms`;
                                    }
                                    if (context.dataset.label?.includes('GPU')) {
                                        return `GPU utilisation: ${formatNumber(value, { maximumFractionDigits: 1 })}%`;
                                    }
                                    return `FPS: ${formatNumber(value, { maximumFractionDigits: 1 })}`;
                                },
                            },
                        },
                    },
                },
            });
        } else {
            livePerformanceChart.data.labels = labels.length ? labels : ['Waiting for data'];
            livePerformanceChart.data.datasets[0].data = labels.length ? fpsData : [0];
            livePerformanceChart.data.datasets[1].data = labels.length ? frameTimeData : [0];
            livePerformanceChart.data.datasets[2].data = labels.length ? gpuData : [0];
            livePerformanceChart.update('none');
        }
    }

    if (liveErrorChartCanvas) {
        if (!liveErrorChart) {
            liveErrorChart = new Chart(liveErrorChartCanvas, {
                type: 'line',
                data: {
                    labels: labels.length ? labels : ['Waiting for data'],
                    datasets: [
                        {
                            label: 'Errors / sample',
                            data: labels.length ? errorData : [0],
                            borderColor: 'rgba(248, 113, 113, 0.9)',
                            backgroundColor: 'rgba(248, 113, 113, 0.2)',
                            tension: 0.25,
                            fill: true,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: 'Errors / sample' },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (context) =>
                                    `Errors: ${formatNumber(context.parsed.y, { maximumFractionDigits: 2 })}`,
                            },
                        },
                    },
                },
            });
        } else {
            liveErrorChart.data.labels = labels.length ? labels : ['Waiting for data'];
            liveErrorChart.data.datasets[0].data = labels.length ? errorData : [0];
            liveErrorChart.update('none');
        }
    }
};

const buildTimelineSeries = (costs = {}) => {
    const series = costs.series?.timeline;
    if (!Array.isArray(series) || series.length === 0) {
        return { labels: [], baseline: [], current: [] };
    }
    const labels = [];
    const baseline = [];
    const current = [];
    series.forEach((point) => {
        labels.push(formatDateTime(point.timestamp));
        baseline.push(point.baseline_cost_per_frame);
        current.push(point.current_cost_per_frame);
    });
    return { labels, baseline, current };
};

const buildStackedSeries = (costs = {}) => {
    const sequenceSeries = Array.isArray(costs.series?.by_sequence)
        ? costs.series.by_sequence
        : [];
    const pnlContributions = Array.isArray(costs.pnl?.contributions)
        ? costs.pnl.contributions
        : [];

    const labels = [];
    const baseline = [];
    const current = [];
    const pnlDelta = [];

    sequenceSeries.forEach((entry) => {
        labels.push(entry.sequence ?? 'Sequence');
        baseline.push(entry.baseline_cost_per_frame ?? costs.cost_per_frame?.baseline ?? 0);
        current.push(entry.current_cost_per_frame ?? costs.cost_per_frame?.current ?? 0);
        pnlDelta.push(0);
    });

    pnlContributions.forEach((contribution) => {
        labels.push(contribution.factor ?? 'P&L factor');
        baseline.push(0);
        current.push(0);
        pnlDelta.push(contribution.delta_cost ?? 0);
    });

    return { labels, baseline, current, pnlDelta };
};

const renderMetricTrendChart = (timeline = []) => {
    if (!metricsTrendChartCanvas || typeof Chart === 'undefined') {
        return;
    }

    const points = Array.isArray(timeline) ? timeline : [];
    const labels = points.map((point) => formatDateTime(point.timestamp));
    const fpsData = points.map((point) => point.fps ?? 0);
    const frameTimeData = points.map((point) => point.frame_time_ms ?? 0);
    const gpuData = points.map((point) => point.gpu_utilisation ?? 0);

    if (metricsTrendChart) {
        metricsTrendChart.destroy();
    }

    metricsTrendChart = new Chart(metricsTrendChartCanvas, {
        type: 'line',
        data: {
            labels: labels.length ? labels : ['No data'],
            datasets: [
                {
                    label: 'FPS',
                    data: labels.length ? fpsData : [0],
                    borderColor: 'rgba(59, 130, 246, 0.8)',
                    backgroundColor: 'rgba(59, 130, 246, 0.25)',
                    tension: 0.2,
                    yAxisID: 'fps',
                },
                {
                    label: 'Frame time (ms)',
                    data: labels.length ? frameTimeData : [0],
                    borderColor: 'rgba(234, 88, 12, 0.8)',
                    backgroundColor: 'rgba(234, 88, 12, 0.2)',
                    tension: 0.2,
                    yAxisID: 'frameTime',
                },
                {
                    label: 'GPU utilisation (%)',
                    data: labels.length ? gpuData : [0],
                    borderColor: 'rgba(34, 197, 94, 0.85)',
                    backgroundColor: 'rgba(34, 197, 94, 0.25)',
                    tension: 0.2,
                    yAxisID: 'gpu',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            stacked: false,
            scales: {
                fps: {
                    type: 'linear',
                    position: 'left',
                    title: { display: true, text: 'FPS' },
                },
                frameTime: {
                    type: 'linear',
                    position: 'right',
                    title: { display: true, text: 'Frame time (ms)' },
                    grid: { drawOnChartArea: false },
                },
                gpu: {
                    type: 'linear',
                    position: 'right',
                    offset: true,
                    title: { display: true, text: 'GPU utilisation (%)' },
                    grid: { drawOnChartArea: false },
                    suggestedMin: 0,
                    suggestedMax: 100,
                },
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const value = context.parsed.y;
                            if (context.dataset.label?.includes('Frame time')) {
                                return `Frame time: ${formatNumber(value, { maximumFractionDigits: 1 })} ms`;
                            }
                            if (context.dataset.label?.includes('GPU')) {
                                return `GPU utilisation: ${formatNumber(value, { maximumFractionDigits: 1 })}%`;
                            }
                            return `FPS: ${formatNumber(value, { maximumFractionDigits: 1 })}`;
                        },
                    },
                },
            },
        },
    });
};

const renderCostCharts = (costs = {}) => {
    if (typeof Chart === 'undefined') {
        return;
    }

    const currency = costs.currency || costs.baseline?.currency;
    const timeline = buildTimelineSeries(costs);
    const stacked = buildStackedSeries(costs);

    const timelineLabels = timeline.labels.length ? timeline.labels : ['Baseline'];
    const baselineSeries = timeline.baseline.length
        ? timeline.baseline
        : [costs.cost_per_frame?.baseline ?? 0];
    const currentSeries = timeline.current.length
        ? timeline.current
        : [costs.cost_per_frame?.current ?? 0];

    if (costTrendChartCanvas) {
        if (costTrendChart) {
            costTrendChart.destroy();
        }
        costTrendChart = new Chart(costTrendChartCanvas, {
            type: 'line',
            data: {
                labels: timelineLabels,
                datasets: [
                    {
                        label: 'Baseline cost/frame',
                        data: baselineSeries,
                        borderColor: 'rgba(59, 130, 246, 0.8)',
                        backgroundColor: 'rgba(59, 130, 246, 0.3)',
                        tension: 0.25,
                        fill: false,
                    },
                    {
                        label: 'Current cost/frame',
                        data: currentSeries,
                        borderColor: 'rgba(16, 185, 129, 0.9)',
                        backgroundColor: 'rgba(16, 185, 129, 0.25)',
                        tension: 0.25,
                        fill: false,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: currency ? `Cost per frame (${currency})` : 'Cost per frame',
                        },
                    },
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const value = context.parsed.y;
                                return currency ? formatCurrency(value, currency) : `${value}`;
                            },
                        },
                    },
                },
            },
        });
    }

    if (pnlBreakdownChartCanvas) {
        if (pnlBreakdownChart) {
            pnlBreakdownChart.destroy();
        }

        const chartLabels = stacked.labels.length ? stacked.labels : ['Baseline', 'Current'];
        const baselineValues = stacked.labels.length
            ? stacked.baseline
            : [costs.cost_per_frame?.baseline ?? 0, 0];
        const currentValues = stacked.labels.length
            ? stacked.current
            : [0, costs.cost_per_frame?.current ?? 0];
        const pnlValues = stacked.labels.length ? stacked.pnlDelta : [];

        pnlBreakdownChart = new Chart(pnlBreakdownChartCanvas, {
            type: 'bar',
            data: {
                labels: chartLabels,
                datasets: [
                    {
                        label: 'Baseline cost/frame',
                        data: baselineValues,
                        backgroundColor: 'rgba(59, 130, 246, 0.6)',
                        stack: 'per-frame',
                    },
                    {
                        label: 'Current cost/frame',
                        data: currentValues,
                        backgroundColor: 'rgba(16, 185, 129, 0.7)',
                        stack: 'per-frame',
                    },
                ].concat(
                    pnlValues.length
                        ? [
                              {
                                  label: 'P&L delta',
                                  data: pnlValues,
                                  backgroundColor: 'rgba(249, 115, 22, 0.7)',
                                  stack: 'pnl',
                              },
                          ]
                        : []
                ),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        stacked: true,
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: currency ? `Cost (${currency})` : 'Cost',
                        },
                    },
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const value = context.parsed.y;
                                return currency ? formatCurrency(value, currency) : `${value}`;
                            },
                        },
                    },
                },
            },
        });
    }
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

const fetchRiskHeatmap = async (params) => {
    if (riskStatus) {
        riskStatus.textContent = 'Loading risk map…';
    }
    try {
        const search = params?.toString ? params.toString() : '';
        const url = search ? `./analytics/risk-heatmap?${search}` : './analytics/risk-heatmap';
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('Failed to fetch risk heatmap');
        }
        const risks = await response.json();
        riskHeatmapData = Array.isArray(risks) ? risks : [];
        applyRiskFilters();
        if (riskStatus) {
            riskStatus.textContent = riskHeatmapData.length ? 'Updated' : 'No risk indicators';
        }
    } catch (error) {
        console.error(error);
        if (riskStatus) {
            riskStatus.textContent = 'Unable to load risk heatmap';
            riskStatus.className = 'badge warning';
        }
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
        const range = applyTimeRangeParams(params);
        const [summaryResponse, costResponse] = await Promise.all([
            fetch(`./dashboard/summary?${params.toString()}`),
            fetch(`./analytics/costs?${params.toString()}`),
        ]);

        if (!summaryResponse.ok) {
            throw new Error('Failed to load summary');
        }

        const summary = await summaryResponse.json();
        const costAnalytics = costResponse.ok ? await costResponse.json() : null;
        const windowLabel = summary.window
            ? `${formatDateTime(summary.window.from)} – ${formatDateTime(summary.window.to)}`
            : `${formatDateTime(range.from)} – ${formatDateTime(range.to)}`;
        summaryGenerated.textContent = windowLabel;
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
        renderCostCharts(costAnalytics ?? summary.costs ?? {});
        renderMetricTrendChart(summary.metrics?.timeline ?? []);
        fetchRiskHeatmap(params).catch(() => {});
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

if (riskSort) {
    riskSort.addEventListener('change', applyRiskFilters);
}

if (riskFilter) {
    riskFilter.addEventListener('change', applyRiskFilters);
}

if (optimizationForm) {
    optimizationForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const scenario = parseOptimizationScenario();
        optimizationState.scenarios.push(scenario);
        renderOptimizationQueue();
        resetOptimizationForm();
        setOptimizationBadge('Scenario queued. Run backtest to compare.', 'success');
    });
}

if (optimizationRunButton) {
    optimizationRunButton.addEventListener('click', () => {
        runOptimizationBacktest().catch(() => {});
    });
}

if (optimizationClearButton) {
    optimizationClearButton.addEventListener('click', () => {
        optimizationState.scenarios = [];
        renderOptimizationQueue();
        resetOptimizationForm();
        setOptimizationBadge('Scenarios cleared.', 'muted');
    });
}

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
        const params = new URLSearchParams();
        applyTimeRangeParams(params);
        const response = await fetch(`./reports/daily?${params.toString()}`);
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
        applyTimeRangeParams(params);
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

if (timeRange) {
    timeRange.addEventListener('change', () => {
        fetchSummary().catch(() => {});
        loadShots().catch(() => {});
    });
}

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

    const liveSamples = [];

    const setStatus = (badgeText, statusText, state = 'connecting') => {
        const badgeClasses = {
            live: 'badge success',
            paused: 'badge muted',
            connecting: 'badge warning',
            offline: 'badge danger',
        };
        if (streamBadge) {
            streamBadge.className = badgeClasses[state] ?? 'badge warning';
            streamBadge.textContent = badgeText;
        }
        if (streamStatus) {
            streamStatus.textContent = statusText;
        }
    };

    const renderLiveRow = (sample) => {
        const row = document.createElement('tr');
        const gpuText = formatNumber(sample.gpu_utilisation, { maximumFractionDigits: 0 });
        const errorsText = formatNumber(sample.error_count, { maximumFractionDigits: 1 });
        row.innerHTML = `
            <td>${sample.sequence ?? '—'}</td>
            <td>${sample.shot_id ?? '—'}</td>
            <td>${formatNumber(sample.fps, { maximumFractionDigits: 1 })}</td>
            <td>${formatNumber(sample.frame_time_ms, { maximumFractionDigits: 0 })}</td>
            <td>${gpuText}${gpuText === '—' ? '' : '%'}</td>
            <td>${errorsText}</td>
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
    };

    const processSample = (sample = {}) => {
        const parsed = {
            sequence: sample.sequence ?? '—',
            shot_id: sample.shot_id ?? '—',
            fps: Number(sample.fps) || 0,
            frame_time_ms: Number(sample.frame_time_ms) || 0,
            gpu_utilisation: Number(sample.gpu_utilisation ?? sample.gpu ?? sample.gpu_usage) || 0,
            error_count: Number(sample.error_count ?? sample.errors) || 0,
            timestamp: sample.timestamp ?? new Date().toISOString(),
        };
        liveSamples.push(parsed);
        if (liveSamples.length > LIVE_SAMPLE_LIMIT) {
            liveSamples.shift();
        }
        renderLiveRow(parsed);
        updateLiveSummary(parsed);
        renderLiveCharts(liveSamples);
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
                setStatus('Paused', pausedMessage, 'paused');
            } else if (isConnected) {
                setStatus('Live', 'Streaming live render metrics.', 'live');
            } else {
                setStatus('Connecting', 'Attempting to open a WebSocket connection…', 'connecting');
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
            setStatus('Connecting', 'Attempting to open a WebSocket connection…', 'connecting');
        } else {
            setStatus('Paused', 'Live stream paused. Waiting for connection…', 'paused');
        }

        socket.addEventListener('open', () => {
            isConnected = true;
            if (streamToggle) {
                streamToggle.disabled = false;
            }
            if (isPaused) {
                setStatus('Paused', 'Live stream paused.', 'paused');
            } else {
                setStatus('Live', 'Streaming live render metrics.', 'live');
            }
        });

        socket.addEventListener('message', (event) => {
            if (isPaused) {
                return;
            }
            try {
                const sample = JSON.parse(event.data ?? '{}');
                processSample(sample);
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
            setStatus(isPaused ? 'Paused' : 'Reconnecting', pausedMessage, isPaused ? 'paused' : 'connecting');
            scheduleReconnect();
        });

        socket.addEventListener('error', () => {
            isConnected = false;
            setStatus('Offline', 'Unable to connect to the render feed.', 'offline');
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
renderOptimizationQueue();
setOptimizationBadge('Define scenarios to compare against baseline.', 'muted');
populateFilters().catch(() => {});
loadShots().catch(() => {});
startMetricsStream();
