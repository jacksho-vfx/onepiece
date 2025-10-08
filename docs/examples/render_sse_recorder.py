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
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Render service base URL",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("TRAFALGAR_TOKEN", ""),
        help="Bearer token with ROLE_RENDER_READ",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.token:
        raise SystemExit("Missing bearer token. Set --token or TRAFALGAR_TOKEN.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Truncate the file when starting a new capture to avoid stale assertions.
    args.output.write_text("", encoding="utf-8")

    try:
        asyncio.run(capture_events(args.output, args.base_url, args.token))
    except KeyboardInterrupt:
        print("Stopped capture")


if __name__ == "__main__":
    main()
