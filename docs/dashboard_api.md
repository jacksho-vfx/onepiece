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
