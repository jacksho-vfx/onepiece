# Trafalgar Dashboard API

The Trafalgar dashboard exposes a consolidated metrics endpoint that surfaces
status information across ingest, render, and review systems. The endpoint is
protected with bearer token authentication so the aggregated production data can
be shared securely.

## Authentication

Set the `TRAFALGAR_DASHBOARD_TOKEN` environment variable before starting the
FastAPI application. Requests must include the matching bearer token using the
`Authorization` header:

```
Authorization: Bearer <token>
```

If the token is missing the service responds with `503 Service Unavailable` to
indicate the dashboard has not been configured. When an incorrect token is
provided the request is rejected with `401 Unauthorized`.

### Cache administration authentication

The cache inspection and refresh endpoints described below reuse the dashboard
bearer token. Any request to `/admin/cache` without a valid
`Authorization: Bearer <token>` header is rejected with `401 Unauthorized` to
ensure in-memory state cannot be enumerated or flushed anonymously.

## Endpoint: `GET /metrics`

The `/metrics` endpoint returns a JSON document that conforms to the following
schema:

- `status`: aggregate project counts and the number of reconciliation errors.
- `ingest`: recent ingest run counts, the timestamp of the last successful run,
  and the current failure streak.
- `render`: render job totals including breakdowns by status and farm adapter.
- `review`: review playlist activity grouped by project with overall totals.

### Example response

```json
{
  "status": {
    "projects": 4,
    "shots": 128,
    "versions": 512,
    "errors": 3
  },
  "ingest": {
    "counts": {
      "total": 10,
      "successful": 9,
      "failed": 1,
      "running": 0
    },
    "last_success_at": "2024-05-08T09:30:00+00:00",
    "failure_streak": 0
  },
  "render": {
    "jobs": 6,
    "by_status": {
      "completed": 4,
      "running": 1,
      "failed": 1
    },
    "by_farm": {
      "mock": 5,
      "tractor": 1
    }
  },
  "review": {
    "totals": {
      "projects": 3,
      "playlists": 7,
      "clips": 42,
      "shots": 28,
      "duration_seconds": 963.5
    },
    "projects": [
      {
        "project": "alpha",
        "playlists": 3,
        "clips": 18,
        "shots": 12,
        "duration_seconds": 450.0
      }
    ]
  }
}
```

This response mirrors the Pydantic models defined in
`src/apps/trafalgar/web/dashboard.py` and demonstrates the key metrics surfaced
by the dashboard.

## Real-time render and ingest updates

Trafalgar now exposes Server-Sent Events (SSE) and WebSocket feeds so clients
can react to render job and ingest run lifecycle changes without polling.

### Render job streams

- `GET /jobs/stream` – SSE endpoint emitting JSON payloads.
- `GET /jobs/ws` – WebSocket endpoint sending JSON frames.

Each event payload includes an `event` string describing the lifecycle stage and
`job` metadata mirroring `RenderJobMetadata`. Example SSE subscription using
`curl`:

```bash
curl -N http://localhost:8000/jobs/stream
```

Sample event:

```text
data: {"event": "job.created", "job": {"job_id": "stub-1", "status": "queued", "farm": "mock", "farm_type": "stub", "message": null, "request": {...}}}
```

### Ingest run streams

- `GET /runs/stream` – SSE endpoint emitting ingest run updates.
- `GET /runs/ws` – WebSocket endpoint sending JSON frames.

Events carry an `event` string (`run.created`, `run.updated`, or `run.removed`)
and a `run` payload matching the REST responses. Example Python snippet using
`httpx` to consume the SSE feed:

```python
import asyncio
import httpx


async def consume_ingest_events():
    async with httpx.AsyncClient(base_url="http://localhost:8001") as client:
        async with client.stream("GET", "/runs/stream") as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    payload = line.removeprefix("data: ").strip()
                    if payload and payload != "{}":
                        print(payload)


asyncio.run(consume_ingest_events())
```

Slow consumers are automatically trimmed or disconnected to avoid unbounded
buffers; reconnecting restores the stream.

### Operational notes for ingest run lookups

Operators frequently probe the ingest API for specific run identifiers when
triaging ingest incidents. Trafalgar now memoises registry reads so repeated
`404` lookups reuse the most recent snapshot instead of hammering the JSON
registry on disk. The cache is invalidated whenever the registry file changes
and gracefully falls back to the last good snapshot if a concurrent writer
briefly produces malformed JSON. As a result, rapid-fire checks for missing
runs no longer result in transient `500` errors while the registry is being
updated.

## Dashboard caching controls

The dashboard keeps frequently accessed data in memory so high-frequency status
polls do not overwhelm backing services such as ShotGrid. Operators can tune
the cache using environment variables and manage the runtime state via admin
endpoints.

### Environment variables

Set the following environment variables before launching the dashboard to
control cache behaviour:

- `ONEPIECE_DASHBOARD_CACHE_TTL` – duration in seconds that a cached response
  remains valid. Expired entries are lazily refreshed on the next request. Use a
  higher value to avoid repeated ShotGrid queries, or a lower value if you need
  near-real-time updates.
- `ONEPIECE_DASHBOARD_CACHE_MAX_RECORDS` – maximum number of records retained in
  a single cache bucket (for example, version summaries). When the limit is
  exceeded the oldest entries are discarded to prevent unbounded growth.
- `ONEPIECE_DASHBOARD_CACHE_MAX_PROJECTS` – caps the number of projects kept in
  memory when aggregating project dashboards. Projects beyond the limit are
  evicted using least-recently-used ordering so the hottest shows stay cached.

Unset variables fall back to the defaults baked into the service configuration.
Values outside of sane ranges are clamped to guard against accidental runaway
memory usage.

### Admin endpoints: `/admin/cache`

- `GET /admin/cache` – returns a JSON snapshot of the in-memory caches,
  including entry counts, TTL configuration, and the timestamp of the last
  refresh for each bucket.
- `POST /admin/cache` – flushes all caches and triggers background refreshes on
  the next request cycle. The body can be empty; the act of hitting the endpoint
  clears the stores.

Both routes require the standard dashboard bearer token and respond with
`401 Unauthorized` when the token is missing or incorrect. Operators should use
these endpoints sparingly in production—force-flushing large caches can spike
load on ShotGrid or other backing APIs until the cache repopulates.

### On-disk project registry lifecycle

The dashboard persists project metadata to `dashboard-projects.json` within the
application data directory. When the service starts it attempts to hydrate the
registry from ShotGrid; successful responses overwrite the file so the cache on
disk reflects the latest project roster. If ShotGrid is temporarily
unreachable, the in-memory cache is populated from the on-disk JSON so the
dashboard can continue serving project lists without interruption. Once
ShotGrid recovers, the next successful sync refreshes both memory and disk and
prunes projects that have been archived or deleted upstream.

The registry file is periodically pruned by comparing the cached entries with
the authoritative ShotGrid list. Projects missing from ShotGrid are removed
from the JSON snapshot, and the sync timestamp is updated. Operators should
monitor filesystem permissions and available disk space—if the file cannot be
written the dashboard logs a warning and continues using the in-memory view
until persistence succeeds.
