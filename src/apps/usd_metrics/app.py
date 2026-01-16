from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

_db_env = "USD_METRICS_DB_PATH"


@dataclass
class USDMetricRecord:
    dcc: str
    stage: str
    duration_ms: float
    sequence: str | None
    asset: str | None
    occurred_at: datetime
    metadata: Mapping[str, Any]


class USDMetricStore:
    """Persist USD metric samples inside a SQLite backed time-series."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialise(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usd_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dcc TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    sequence TEXT,
                    asset TEXT,
                    duration_ms REAL NOT NULL,
                    occurred_at TEXT NOT NULL,
                    metadata TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_usd_events_timeline
                ON usd_events(occurred_at);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_usd_events_sequence_asset
                ON usd_events(sequence, asset);
                """
            )

    def persist(self, events: Sequence[USDMetricRecord]) -> int:
        if not events:
            return 0

        payload = [
            (
                event.dcc,
                event.stage,
                event.sequence,
                event.asset,
                event.duration_ms,
                event.occurred_at.isoformat(),
                json.dumps(event.metadata),
            )
            for event in events
        ]

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO usd_events (
                    dcc, stage, sequence, asset, duration_ms, occurred_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            conn.commit()
        return len(events)

    def summary(self) -> list[Mapping[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT sequence, asset, stage,
                       COUNT(*) AS samples,
                       AVG(duration_ms) AS avg_duration_ms,
                       MAX(duration_ms) AS max_duration_ms,
                       SUM(duration_ms) AS total_duration_ms
                  FROM usd_events
              GROUP BY sequence, asset, stage
              ORDER BY total_duration_ms DESC
                """
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def bottlenecks(self, *, limit: int = 20) -> list[Mapping[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT sequence, asset,
                       COUNT(*) AS samples,
                       SUM(duration_ms) AS total_duration_ms,
                       MAX(duration_ms) AS worst_case_ms,
                       AVG(duration_ms) AS avg_duration_ms
                  FROM usd_events
              GROUP BY sequence, asset
              ORDER BY total_duration_ms DESC, samples DESC
                 LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]


class MetricEvent(BaseModel):
    dcc: str = Field(..., description="Originating DCC identifier (c4d/unreal/nuke)")
    stage: str = Field(..., description="Operation or phase being timed")
    duration_ms: float = Field(..., gt=0)
    sequence: str | None = Field(None, description="Show or sequence identifier")
    asset: str | None = Field(None, description="Asset or shot identifier")
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("duration_ms")
    @classmethod
    def _duration_is_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("duration_ms must be positive")
        return value


class MetricIngestPayload(BaseModel):
    events: Sequence[MetricEvent]

    @field_validator("events")
    @classmethod
    def _non_empty(cls, events: Sequence[MetricEvent]) -> Sequence[MetricEvent]:
        if not events:
            raise ValueError("events payload cannot be empty")
        return events


def get_store() -> USDMetricStore:
    path = Path(os.getenv(_db_env, "usd_metrics.db"))
    return USDMetricStore(path)


app = FastAPI(title="USD Metrics", version="0.1.0")


@app.post("/events")
def ingest_metrics(
    payload: MetricIngestPayload, store: USDMetricStore = Depends(get_store)
) -> Mapping[str, Any]:
    """Persist timing events into the time-series store."""

    records = [
        USDMetricRecord(
            dcc=event.dcc,
            stage=event.stage,
            sequence=event.sequence,
            asset=event.asset,
            duration_ms=event.duration_ms,
            occurred_at=event.occurred_at,
            metadata=event.metadata,
        )
        for event in payload.events
    ]
    stored = store.persist(records)
    return {"stored": stored}


@app.get("/summary")
def metrics_summary(
    store: USDMetricStore = Depends(get_store),
) -> Sequence[Mapping[str, Any]]:
    return store.summary()


@app.get("/bottlenecks")
def metrics_bottlenecks(
    limit: int = 20, store: USDMetricStore = Depends(get_store)
) -> Sequence[Mapping[str, Any]]:
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")
    return store.bottlenecks(limit=limit)


def _render_bottlenecks(store: USDMetricStore) -> str:
    rows = store.bottlenecks(limit=50)
    if not rows:
        return "<p>No metrics ingested yet.</p>"

    header = (
        "<tr><th>Sequence</th><th>Asset</th><th>Samples</th>"
        "<th>Total ms</th><th>Avg ms</th><th>Worst ms</th></tr>"
    )
    body = "".join(
        (
            "<tr>"
            f"<td>{row.get('sequence') or '—'}</td>"
            f"<td>{row.get('asset') or '—'}</td>"
            f"<td>{row['samples']}</td>"
            f"<td>{round(row['total_duration_ms'], 2)}</td>"
            f"<td>{round(row['avg_duration_ms'], 2)}</td>"
            f"<td>{round(row['worst_case_ms'], 2)}</td>"
            "</tr>"
        )
        for row in rows
    )
    return f"<table><thead>{header}</thead><tbody>{body}</tbody></table>"


@app.get("/", response_class=HTMLResponse)
def index(store: USDMetricStore = Depends(get_store)) -> str:
    table = _render_bottlenecks(store)
    return f"""
    <html>
      <head>
        <title>USD Metrics</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 2rem; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
          th {{ background: #f4f4f4; }}
        </style>
      </head>
      <body>
        <h1>USD Metrics Bottlenecks</h1>
        <p>Aggregated durations grouped by sequence and asset.</p>
        {table}
      </body>
    </html>
    """


__all__ = ["app", "get_store", "USDMetricStore", "USDMetricRecord"]
