# Trafalgar event stream walkthroughs

Trafalgar exposes Server-Sent Events (SSE) and WebSocket feeds that mirror the
render and ingest lifecycle. The examples below show how to subscribe using
`curl`, [`websocat`](https://github.com/vi/websocat), and Python so you can
inspect job progress locally or forward the events into automation.

> **Authentication reminder**
>
> - Render feeds require a bearer token associated with the
>   `ROLE_RENDER_READ` grant.
> - Ingest feeds require a bearer token that includes `ROLE_INGEST_READ`.
>
> The examples assume a token stored in `$TRAFALGAR_TOKEN`. Replace the
> placeholder with a real value or export the environment variable before
> running the commands.

## Render job SSE (`GET /render/jobs/stream`)

The SSE stream emits JSON payloads describing each render job transition.

### Using `curl`

```bash
curl -N \
  -H "Authorization: Bearer $TRAFALGAR_TOKEN" \
  http://localhost:8000/render/jobs/stream
```

The `-N` flag disables buffering so events appear as soon as they arrive. Each
message is delivered as a `data:` line:

```
data: {"event": "job.updated", "job": {"job_id": "mock-42", "status": "running"}}
```

### Python async client

```python
import asyncio
import os
import httpx


async def consume_render_events():
    token = os.environ["TRAFALGAR_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url="http://localhost:8000", headers=headers) as client:
        async with client.stream("GET", "/render/jobs/stream", timeout=None) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload:
                        print(payload)


asyncio.run(consume_render_events())
```

The explicit `timeout=None` prevents the client from closing the stream while it
waits for the next event.

## Render job WebSocket (`GET /render/jobs/ws`)

The WebSocket endpoint delivers the same events as JSON text frames. `websocat`
can connect directly:

```bash
websocat \
  "wss://example.invalid/render/jobs/ws?token=$TRAFALGAR_TOKEN"
```

A Python example using `websockets`:

```python
import asyncio
import json
import os

import websockets


async def consume_render_ws():
    token = os.environ["TRAFALGAR_TOKEN"]
    uri = f"ws://localhost:8000/render/jobs/ws?token={token}"
    async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
        async for message in ws:
            event = json.loads(message)
            print(event)


asyncio.run(consume_render_ws())
```

The `ping_interval` keeps the connection active so idle environments do not time
out.

## Ingest run SSE (`GET /ingest/runs/stream`)

Ingest run updates follow the same structure and include the most recent run
state.

```bash
curl -N \
  -H "Authorization: Bearer $TRAFALGAR_TOKEN" \
  http://localhost:8001/ingest/runs/stream
```

Python clients can reuse the SSE loop from the render example by changing the
endpoint path to `/ingest/runs/stream`.

## Ingest run WebSocket (`GET /ingest/runs/ws`)

```bash
websocat \
  "wss://example.invalid/ingest/runs/ws?token=$TRAFALGAR_TOKEN"
```

Python example:

```python
import asyncio
import json
import os

import websockets


async def consume_ingest_ws():
    token = os.environ["TRAFALGAR_TOKEN"]
    uri = f"ws://localhost:8001/ingest/runs/ws?token={token}"
    async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
        async for message in ws:
            event = json.loads(message)
            print(event)


asyncio.run(consume_ingest_ws())
```

## Troubleshooting

- **401 Unauthorized** – Ensure the bearer token carries the correct role.
  Render endpoints require `ROLE_RENDER_READ`; ingest endpoints require
  `ROLE_INGEST_READ`.
- **Connection closes after a few minutes** – Trafalgar enforces an idle timeout
  on both SSE and WebSocket feeds. Issue periodic keepalive traffic:
  - SSE: send `HEAD /healthz` from a cron job to keep the reverse proxy warm.
  - WebSocket: configure client pings (see `ping_interval` above).
- **Proxy strips the `Authorization` header** – When invoking from automation,
  pass the token via the `token` query parameter instead.

## Optional: integrate SSE into regression tests

The companion script [`render_sse_recorder.py`](./render_sse_recorder.py) records
the SSE feed to a JSONL file so regression suites can assert on job sequencing.
Run it as part of your integration tests or nightly smoke checks.

```python
#!/usr/bin/env python3
"""Capture Trafalgar render SSE events for regression assertions."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx


async def capture_events(output: Path, base_url: str, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=None) as client:
        async with client.stream("GET", "/render/jobs/stream") as response:
            response.raise_for_status()
            with output.open("a", encoding="utf-8") as sink:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        payload = line[6:].strip()
                        if payload:
                            event: Any = json.loads(payload)
                            sink.write(json.dumps(event) + "\n")
                            sink.flush()
                            print(event)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("render-events.jsonl"))
    parser.add_argument("--base-url", default="http://localhost:8000", help="Render service base URL")
    parser.add_argument("--token", default=os.environ.get("TRAFALGAR_TOKEN", ""), help="Bearer token with ROLE_RENDER_READ")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.token:
        raise SystemExit("Missing bearer token. Set --token or TRAFALGAR_TOKEN.")

    # Ensure the parent directory exists before writing the log file.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Truncate the file when starting a new capture to avoid stale assertions.
    args.output.write_text("", encoding="utf-8")

    try:
        asyncio.run(capture_events(args.output, args.base_url, args.token))
    except KeyboardInterrupt:
        print("Stopped capture")


if __name__ == "__main__":
    main()
```

Run the script with:

```bash
python docs/examples/render_sse_recorder.py --output build/render-events.jsonl
```

Your regression suite can then compare the generated JSONL file with a golden
record.
