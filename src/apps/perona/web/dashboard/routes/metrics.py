"""Metrics ingestion and telemetry routes."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse

from apps.perona.web.dashboard import dependencies
from libraries.analytics.perona.engine.engine import PeronaEngine
from libraries.analytics.perona.models import RenderMetric

router = APIRouter(tags=["metrics"])
logger = logging.getLogger(__name__)


def compute_metrics_summary(engine: PeronaEngine) -> dict[str, Any]:
    """Return aggregated statistics for recent render telemetry."""

    def _rounded_mean(total: float, count: int) -> float:
        return round(total / count, 3) if count else 0.0

    total_samples = 0
    total_fps = 0.0
    total_frame_time = 0.0
    total_gpu_utilisation = 0.0
    total_error_count = 0.0

    sequence_stats: dict[str, dict[str, Any]] = {}
    latest_sample: RenderMetric | None = None
    latest_timestamp: datetime | None = None

    for sample in engine.stream_render_metrics():
        total_samples += 1
        total_fps += sample.fps
        total_frame_time += sample.frame_time_ms
        total_gpu_utilisation += sample.gpu_utilisation
        total_error_count += sample.error_count

        entry = sequence_stats.setdefault(
            sample.sequence,
            {
                "shots": set(),
                "count": 0,
                "fps_total": 0.0,
                "frame_time_total": 0.0,
                "gpu_utilisation_total": 0.0,
                "error_total": 0.0,
            },
        )
        entry["shots"].add(sample.shot_id)
        entry["count"] += 1
        entry["fps_total"] += sample.fps
        entry["frame_time_total"] += sample.frame_time_ms
        entry["gpu_utilisation_total"] += sample.gpu_utilisation
        entry["error_total"] += sample.error_count

        if latest_timestamp is None or sample.timestamp > latest_timestamp:
            latest_timestamp = sample.timestamp
            latest_sample = sample

    if total_samples == 0:
        return {
            "total_samples": 0,
            "averages": {
                "fps": 0.0,
                "frame_time_ms": 0.0,
                "gpu_utilisation": 0.0,
                "error_count": 0.0,
            },
            "sequences": [],
            "latest_sample": None,
        }

    overall_averages = {
        "fps": _rounded_mean(total_fps, total_samples),
        "frame_time_ms": _rounded_mean(total_frame_time, total_samples),
        "gpu_utilisation": _rounded_mean(total_gpu_utilisation, total_samples),
        "error_count": _rounded_mean(total_error_count, total_samples),
    }

    sequences_summary = [
        {
            "sequence": name,
            "shots": len(data["shots"]),
            "avg_fps": _rounded_mean(data["fps_total"], data["count"]),
            "avg_frame_time_ms": _rounded_mean(data["frame_time_total"], data["count"]),
            "avg_gpu_utilisation": _rounded_mean(
                data["gpu_utilisation_total"], data["count"]
            ),
            "avg_error_count": _rounded_mean(data["error_total"], data["count"]),
        }
        for name, data in sorted(sequence_stats.items())
    ]

    latest_payload = None
    if latest_sample is not None:
        latest_payload = RenderMetric.from_entity(latest_sample).model_dump(
            mode="json", by_alias=True
        )

    return {
        "total_samples": total_samples,
        "averages": overall_averages,
        "sequences": sequences_summary,
        "latest_sample": latest_payload,
    }


@router.post(
    "/api/metrics",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(dependencies.require_metrics_auth)],
)
async def ingest_render_metrics(
    payload: dependencies.RenderMetricBatch, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Accept render metrics and persist them asynchronously."""

    records = payload.to_serialisable()
    if not records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No metrics supplied."
        )

    max_batch_size = dependencies.metrics_max_batch_size()
    record_count = len(records)
    if record_count > max_batch_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Batch size {record_count} exceeds the configured limit of "
                f"{max_batch_size} records."
            ),
        )

    try:
        background_tasks.add_task(dependencies.persist_metrics, records)
    except Exception:
        correlation_id = str(uuid4())
        logger.exception(
            "Failed to enqueue metrics persistence task.",
            extra={"correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Unable to enqueue metrics persistence task. "
                f"Correlation ID: {correlation_id}"
            ),
        )

    return {"status": "accepted", "enqueued": record_count}


@router.get("/render-feed", response_model=list[RenderMetric])
def render_feed(
    limit: int = Query(30, ge=1, le=250),
    sequence: str | None = Query(None),
    shot_id: str | None = Query(None),
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> list[RenderMetric]:
    """Return recent render telemetry samples for dashboard widgets."""

    metrics = [
        RenderMetric.from_entity(metric)
        for metric in engine.stream_render_metrics(
            limit, sequence=sequence, shot_id=shot_id
        )
    ]
    return metrics


@router.get(
    "/render-feed/live",
    dependencies=[Depends(dependencies.require_metrics_auth)],
)
async def render_feed_stream(
    limit: int = Query(30, ge=1, le=250),
    sequence: str | None = Query(None),
    shot_id: str | None = Query(None),
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> StreamingResponse:
    """Stream telemetry samples using newline delimited JSON."""

    async def _generator() -> Any:
        for metric in engine.stream_render_metrics(
            limit, sequence=sequence, shot_id=shot_id
        ):
            model = RenderMetric.from_entity(metric)
            payload = model.model_dump(mode="json", by_alias=True)
            yield json.dumps(payload) + "\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(_generator(), media_type="application/x-ndjson")


@router.get("/metrics")
def metrics_summary(
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> dict[str, Any]:
    """Return aggregated statistics for recent render telemetry."""

    return compute_metrics_summary(engine)


@router.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket) -> None:
    """Stream render telemetry samples over a WebSocket connection."""

    await dependencies.require_metrics_websocket_auth(websocket)
    await websocket.accept()
    try:
        while True:
            engine = dependencies.get_engine(refresh=False)
            for sample in engine.stream_render_metrics(limit=30):
                payload = RenderMetric.from_entity(sample).model_dump(
                    mode="json", by_alias=True
                )
                await websocket.send_json(payload)
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


__all__ = ["router", "compute_metrics_summary"]
