# Perona dashboard operations

[Back to the Perona overview in the README](../README.md#operating-the-perona-dashboard)

The Perona CLI and FastAPI service ship together so teams can launch the web dashboard, inspect configuration, and script against
render and finance telemetry. This guide captures the day-to-day commands, configuration layers, and HTTP endpoints that were
added for the 1.0 release.

## CLI usage

### Inspect resolved settings

Use `perona settings` to display the merged configuration that the dashboard engine will load:

```bash
# Print a human-readable table sourced from defaults and overrides
perona settings

# Load an explicit settings file and display the resolved table
perona settings --settings-path /opt/perona/perona.toml

# Highlight how overrides differ from the bundled defaults
perona settings --settings-path /opt/perona/perona.toml --diff
```

Key options:

- `--settings-path PATH` &mdash; optional, validates that the file exists and is readable before using it.
- `--diff/--no-diff` &mdash; opt-in, appends a comparison against the packaged defaults (works with both table and JSON output).
- `--format table|json` &mdash; switches between the aligned table (default) and JSON output for automation.

The JSON output doubles as an export helper so downstream tooling can persist the configuration snapshot:

```bash
# Export the effective settings to disk for audit trails or CI artefacts
perona settings --format json > build/perona-settings.json
```

### Reload settings without restarting

Use `perona settings reload` to force a running dashboard instance to rebuild its engine cache after editing override files:

```bash
# Reload a dashboard running on the default localhost port
perona settings reload

# Target a remote deployment explicitly
perona settings reload --url https://perona.internal.example.com

# Refresh the settings for a locally imported FastAPI app without HTTP
perona settings reload --local
```

Key options:

- `--url URL` &mdash; optional, points the CLI at a specific dashboard base URL. Falls back to the `PERONA_DASHBOARD_URL`
  environment variable or `http://127.0.0.1:8065`.
- `--local` &mdash; bypasses HTTP entirely and triggers the cache invalidator directly. Handy for local development when the
  FastAPI app is imported inside the same Python process.

### Estimate render costs

Use `perona cost estimate` to model the spend for a prospective render workload without hitting the API:

```bash
# Produce a tabular breakdown of costs
perona cost estimate --frame-count 480 --average-frame-time-ms 110 --gpu-hourly-rate 9.25 \
  --storage-gb 15 --storage-rate-per-gb 0.45

# Emit JSON for automation pipelines
perona cost estimate --frame-count 120 --average-frame-time-ms 80 --gpu-hourly-rate 7.5 \
  --format json
```

Key options:

- `--frame-count` &mdash; required, total number of frames being rendered.
- `--average-frame-time-ms` &mdash; required, mean render time per frame in milliseconds.
- `--gpu-hourly-rate` &mdash; required, cost of GPU usage per hour.
- `--storage-gb`, `--storage-rate-per-gb`, `--data-egress-gb`, `--egress-rate-per-gb`, `--misc-costs` &mdash; optional inputs for ancillary spend.
- `--format table|json` &mdash; toggles between the tabular and JSON renderings of the breakdown.
- `--settings-path PATH` &mdash; optional, seeds the engine with a custom settings file before calculating costs.

### Launch the web dashboard

Use `perona web dashboard` to boot the uvicorn-powered FastAPI service:

```bash
# Local development defaults
perona web dashboard

# Bind to all interfaces, customise logging, and load a bespoke settings file
perona web dashboard --host 0.0.0.0 --port 8065 --log-level debug \
  --settings-path ./ops/perona.toml --reload
```

Available options:

| Option | Purpose |
| --- | --- |
| `--host / -h` | Interface to bind the server to (defaults to `127.0.0.1`). |
| `--port / -p` | TCP port for uvicorn (defaults to `8065`). |
| `--reload/--no-reload` | Enable development auto-reloads (defaults to disabled). |
| `--log-level` | Uvicorn log level (defaults to `info`). |
| `--settings-path` | Optional configuration override consumed before the server starts. |

When a valid settings file is supplied the CLI exports `PERONA_SETTINGS_PATH` into the environment so the FastAPI app reads the
same overrides on boot.

### Version discovery

Run `perona version` to print the packaged dashboard build number so deployment scripts can confirm the expected artefact.

## Configuration layers

Perona resolves configuration from layered TOML files:

1. The CLI-provided `--settings-path` (when set).
2. The `PERONA_SETTINGS_PATH` environment variable (respected by both CLI and API).
3. The baked-in defaults located at `src/apps/perona/defaults.toml`.

Missing, unreadable, or invalid TOML files trigger warnings via the `apps.perona.engine` logger and fall back to defaults. Keep
overrides under version control to ensure reproducible deployments.

## HTTP API reference

Perona's FastAPI surface ships alongside the CLI. Endpoints are rooted at the uvicorn base URL (for example,
`http://127.0.0.1:8065`). The `/settings` endpoint mirrors the [`perona settings`](#inspect-resolved-settings) CLI output so
automation can consume the resolved configuration directly from the API.

### Settings snapshot

- `GET /settings` &mdash; returns the resolved configuration powering the dashboard, including any overrides detected on disk or
  via `PERONA_SETTINGS_PATH`.
- `POST /settings/reload` &mdash; clears the engine cache, rebuilds the configuration from disk, and returns the refreshed summary.

```bash
curl http://127.0.0.1:8065/settings | jq
```

Example response:

```json
{
  "baseline_cost_input": {
    "frame_count": 2688,
    "average_frame_time_ms": 142.0,
    "gpu_hourly_rate": 8.75,
    "gpu_count": 64,
    "render_hours": 0.0,
    "render_farm_hourly_rate": 5.25,
    "storage_gb": 12.4,
    "storage_rate_per_gb": 0.38,
    "data_egress_gb": 3.8,
    "egress_rate_per_gb": 0.19,
    "misc_costs": 220.0
  },
  "target_error_rate": 0.012,
  "pnl_baseline_cost": 18240.0,
  "settings_path": "/opt/perona/perona.toml"
}
```

When no overrides are detected the `settings_path` field is `null`. Supplying `perona web dashboard --settings-path` (or
exporting `PERONA_SETTINGS_PATH`) ensures the API echoes the same path so release diffing can confirm the expected file was
loaded.

### Health checks

- `GET /health` &mdash; returns `{ "status": "ok" }` for uptime monitoring.

```bash
curl http://127.0.0.1:8065/health
```

### Render feeds

- `GET /render-feed?limit=30` &mdash; returns the latest render metrics as JSON.
- `GET /render-feed/live?limit=30` &mdash; streams newline-delimited JSON for dashboards that follow live metrics.

```bash
# Fetch the most recent 10 samples
curl "http://127.0.0.1:8065/render-feed?limit=10"

# Follow the live NDJSON feed
curl -N "http://127.0.0.1:8065/render-feed/live?limit=50"
```

Each metric contains sequence, shot identifiers, frame timing, and GPU/cache health indicators.

### Cost estimation

- `POST /cost/estimate` &mdash; accepts a JSON body that mirrors the `perona settings` cost inputs and returns a detailed cost
  breakdown.

```bash
curl -X POST http://127.0.0.1:8065/cost/estimate \
  -H "Content-Type: application/json" \
  -d '{
        "frame_count": 250,
        "average_frame_time_ms": 115.0,
        "gpu_hourly_rate": 9.25,
        "render_farm_hourly_rate": 6.0,
        "storage_gb": 10.5,
        "storage_rate_per_gb": 0.42
      }'
```

### Risk and profitability

- `GET /risk-heatmap` &mdash; surfaces risk indicators per shot, including error rates and cache stability drivers.
- `GET /pnl` &mdash; returns baseline versus current spend alongside narrative contributions.

### Optimisation backtests

- `POST /optimization/backtest` &mdash; accepts optimisation scenarios and responds with the simulated baseline and scenario outcomes.
  Supply one or more scenario objects to compare GPU counts, hourly rates, or render-time scalars.

### Shot lifecycle timelines

- `GET /shots/lifecycle` &mdash; returns tracked shots with their production stages, durations, and stage-specific metrics.

```bash
curl http://127.0.0.1:8065/shots/lifecycle | jq '.[0]'
```

## Pre-release review checklist

Before cutting a release confirm:

- CLI commands above match `perona --help` output, including the [`perona settings`](#inspect-resolved-settings) JSON diff
  helpers, the [`perona cost estimate`](#estimate-render-costs) command, and the [`perona web dashboard`](#launch-the-web-dashboard)
  reload toggles.
- The configuration resolution order reflects the latest engine defaults and aligns with the [`GET /settings`](#settings-snapshot)
  response payload.
- API responses align with the FastAPI models (update curl examples if schemas change), especially the [`/settings`](#settings-snapshot)
  and [`/cost/estimate`](#cost-estimation) endpoints.

Once verified, update this document and cross-check the README link to keep operator documentation consistent.
