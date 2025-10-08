# Render API capability schema

The Trafalgar render service exposes the `/farms` endpoint so CLI tools and UI
widgets can discover registered adapters along with the behaviour they support.
The response now returns structured capability descriptors for each adapter.

```json
{
  "farms": [
    {
      "name": "mock",
      "description": "Mock render farm for testing and demos.",
      "capabilities": {
        "priority": {
          "default": 50,
          "minimum": 0,
          "maximum": 100
        },
        "chunking": {
          "enabled": true,
          "minimum": 1,
          "maximum": 10,
          "default": 5
        },
        "cancellation": {
          "supported": false
        }
      }
    }
  ]
}
```

The descriptors can be interpreted as follows:

- `priority` – documents the default priority applied by the service when a
  submission omits one, along with the adapter's minimum and maximum allowed
  range. Values outside this range are rejected by the CLI and API.
- `chunking` – indicates whether the adapter supports frame chunking and, when
  enabled, the allowed range plus the default chunk size. Clients should hide or
  disable chunk controls when `enabled` is `false`.
- `cancellation` – signals whether the adapter implements the cancellation hook
  consumed by the job management endpoints. Interfaces can conditionally expose
  cancel buttons based on this flag.

These descriptors align with the validation logic used by the CLI
(`python -m apps.onepiece render submit`) so interactive tools can surface the
same guard rails and defaults without reaching into adapter internals.

## Extending the adapter registry

The Trafalgar service now sources its adapter list from the runtime
`RenderSubmissionService` registry. Projects integrating bespoke farm managers
can register additional adapters during startup:

```python
from apps.trafalgar.web.render import get_render_service

service = get_render_service()
service.register_adapter("studiofarm", submit_to_studio_farm)
```

The API will immediately accept `studiofarm` submissions and expose the key via
`/farms` without requiring code changes. Request validation uses the same
registry, so bespoke adapters can be surfaced to clients and tests by
registering them with the shared service instance.

## Streaming walkthroughs

Need end-to-end examples for monitoring render jobs? The
[event stream walkthroughs](./examples/trafalgar_event_streams.md) demonstrate
how to subscribe to `/render/jobs/stream` and `/render/jobs/ws` using `curl`,
`websocat`, and Python clients, including authentication and keepalive tips.

## Render job history retention

Trafalgar keeps an in-memory history of submitted jobs and can optionally
persist snapshots to disk. Operators can tune the size and lifetime of this
history with the following environment variables:

| Variable | Example | Behaviour |
| --- | --- | --- |
| `TRAFALGAR_RENDER_JOBS_PATH` | `/var/lib/trafalgar/render_jobs.json` | Enables the on-disk job store. When set, the service reloads job history on startup and writes updates after each submission or status change. |
| `TRAFALGAR_RENDER_JOBS_HISTORY_LIMIT` | `500` | Caps the in-memory history. When the limit is exceeded, the oldest records are pruned, SSE subscribers receive a `job.removed` event, and the `/render/health` metrics update their prune counters. Use this to bound memory usage when farms submit thousands of jobs. |
| `TRAFALGAR_RENDER_JOBS_RETENTION_HOURS` | `168` | Applies age-based pruning to the persistent store. Entries older than the configured number of hours are removed during each save as well as on service startup. For example, `168` keeps a rolling seven-day window of historical jobs on disk. |

Omitting the limit or retention variables leaves the in-memory store unbounded
and keeps all persisted records, respectively. Negative or zero values are
ignored and logged.

### Monitoring retention with `/render/health`

The `/render/health` endpoint returns the service status alongside job-history
metrics:

```json
{
  "status": "ok",
  "render_history": {
    "history_size": 120,
    "history_limit": 500,
    "history_pruned_total": 12,
    "last_history_prune_at": "2024-04-15T09:30:12.481921+00:00",
    "last_history_pruned": 4,
    "store": {
      "retained_records": 480,
      "last_pruned_count": 10,
      "total_pruned": 42,
      "last_pruned_at": "2024-04-15T09:30:12.478112+00:00",
      "last_load_at": "2024-04-15T08:59:01.004882+00:00",
      "last_save_at": "2024-04-15T09:30:12.483820+00:00",
      "last_rotation_at": "2024-04-15T09:30:12.483095+00:00",
      "last_rotation_error": null,
      "retention_seconds": 604800
    }
  }
}
```

Field meanings:

- `history_size` – the number of jobs currently cached in memory.
- `history_limit` – the configured cap (or `null` when unlimited).
- `history_pruned_total` – cumulative count of jobs removed because the limit
  was exceeded.
- `last_history_prune_at` – timestamp of the most recent in-memory prune.
- `last_history_pruned` – number of jobs removed during the last prune
  operation.
- `store.*` – metrics provided by the optional persistent store:
  - `retained_records` – number of jobs kept on disk after the last save or
    load.
  - `last_pruned_count` / `total_pruned` / `last_pruned_at` – activity from
    retention-based pruning when `TRAFALGAR_RENDER_JOBS_RETENTION_HOURS` is set.
  - `last_load_at` / `last_save_at` – timestamps of the most recent disk I/O.
  - `last_rotation_at` / `last_rotation_error` – rotation activity when
    creating `.bak` snapshots before writes.
  - `retention_seconds` – retention window expressed in seconds (or `null`
    when unbounded).

The `store` field is `null` when the on-disk store is disabled. These metrics
allow SREs to alert when pruning is frequent, retention windows are too small,
or the service stops writing to disk.

### Example configuration

Set the job store path and retention knobs using your preferred configuration
mechanism. For example, a `.env` file consumed by `uvicorn` or `trafalgar web
render` can look like:

```dotenv
TRAFALGAR_RENDER_JOBS_PATH=/var/lib/trafalgar/render_jobs.json
TRAFALGAR_RENDER_JOBS_HISTORY_LIMIT=500
TRAFALGAR_RENDER_JOBS_RETENTION_HOURS=168
```

For systemd deployments, apply the same settings via the unit file:

```ini
[Service]
Environment="TRAFALGAR_RENDER_JOBS_PATH=/var/lib/trafalgar/render_jobs.json"
Environment="TRAFALGAR_RENDER_JOBS_HISTORY_LIMIT=500"
Environment="TRAFALGAR_RENDER_JOBS_RETENTION_HOURS=168"
```

Restarting the service reloads retained jobs from disk, prunes entries older
than seven days, and keeps the newest 500 jobs in memory for API responses and
event broadcasting.
