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
