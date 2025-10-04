"""FastAPI application exposing ingest run summaries for Trafalgar."""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence, cast

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from libraries.ingest.registry import IngestRunRecord, IngestRunRegistry
from libraries.ingest.service import IngestReport, IngestedMedia

logger = structlog.getLogger(__name__)


def _serialise_media(media: IngestedMedia) -> Mapping[str, Any]:
    return {
        "path": str(media.path),
        "bucket": media.bucket,
        "key": media.key,
        "media_info": asdict(media.media_info),
    }


def _serialise_invalid(entries: Iterable[tuple[Any, str]]) -> list[Mapping[str, Any]]:
    return [{"path": str(path), "reason": reason} for path, reason in entries]


def _serialise_report(report: IngestReport) -> Mapping[str, Any]:
    return {
        "processed": [_serialise_media(media) for media in report.processed],
        "invalid": _serialise_invalid(report.invalid),
        "processed_count": report.processed_count,
        "invalid_count": report.invalid_count,
    }


def _serialise_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialise_run(record: IngestRunRecord) -> Mapping[str, Any]:
    return {
        "id": record.run_id,
        "started_at": _serialise_datetime(record.started_at),
        "completed_at": _serialise_datetime(record.completed_at),
        "status": "completed" if record.completed_at else "running",
        "report": _serialise_report(record.report),
    }


class IngestRunProvider:
    """Provide ingest run metadata by consulting the shared registry."""

    def __init__(self, registry: IngestRunRegistry | None = None) -> None:
        self._registry = registry or IngestRunRegistry()

    def load_recent_runs(self, limit: int | None = None) -> Sequence[IngestRunRecord]:
        return cast(Sequence[IngestRunRecord], self._registry.load_recent(limit))

    def get_run(self, run_id: str) -> IngestRunRecord | None:
        return self._registry.get(run_id)


class IngestRunService:
    """Transform ingest run records into API-friendly payloads."""

    def __init__(
        self,
        provider: IngestRunProvider | None = None,
        *,
        serializer: Callable[[IngestRunRecord], Mapping[str, Any]] | None = None,
    ) -> None:
        self._provider = provider or IngestRunProvider()
        self._serialize = serializer or _serialise_run

    def list_runs(self, limit: int) -> list[Mapping[str, Any]]:
        records = self._provider.load_recent_runs(limit)
        return [self._serialize(record) for record in records]

    def get_run(self, run_id: str) -> Mapping[str, Any]:
        record = self._provider.get_run(run_id)
        if record is None:
            raise KeyError(run_id)
        return self._serialize(record)


def get_ingest_run_service() -> IngestRunService:  # pragma: no cover - runtime wiring
    return IngestRunService()


app = FastAPI(title="OnePiece Ingest Runs", version="1.0.0")


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    logger.info("ingest.request.start", method=request.method, path=request.url.path)
    response = await call_next(request)
    logger.info(
        "ingest.request.complete",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    return response


@app.get("/runs")
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    service: IngestRunService = Depends(get_ingest_run_service),
) -> JSONResponse:
    payload = service.list_runs(limit)
    return JSONResponse(content=payload)


@app.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    service: IngestRunService = Depends(get_ingest_run_service),
) -> JSONResponse:
    try:
        payload = service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return JSONResponse(content=payload)
