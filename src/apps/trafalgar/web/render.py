"""FastAPI application exposing render job submission endpoints."""

from __future__ import annotations

import getpass
from typing import Awaitable, Callable, Mapping, Sequence

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.responses import Response

from apps.onepiece.render.submit import DCC_CHOICES, FARM_ADAPTERS
from libraries.render.base import RenderSubmissionError, SubmissionResult
from libraries.render.models import RenderAdapter

logger = structlog.get_logger(__name__)

FARM_DESCRIPTIONS: Mapping[str, str] = {
    "deadline": "Autodesk Deadline render manager (stub).",
    "tractor": "Pixar Tractor render farm (stub).",
    "opencue": "OpenCue render manager (stub).",
    "mock": "Mock render farm for testing and demos.",
}


class FarmInfo(BaseModel):
    """Metadata describing a render farm adapter."""

    name: str = Field(..., description="Adapter identifier used by the API and CLI.")
    description: str = Field(
        ..., description="Human readable description of the adapter."
    )


class FarmsResponse(BaseModel):
    """Response payload enumerating available render farm adapters."""

    farms: Sequence[FarmInfo]


class RenderJobRequest(BaseModel):
    """Request payload mirroring the CLI submission options."""

    dcc: str = Field(
        ..., description="Digital content creation package (e.g. maya, nuke)."
    )
    scene: str = Field(
        ..., description="Path to the scene file that should be rendered."
    )
    frames: str = Field(
        "1-100",
        description="Frame range to render, supporting Deadline style notation (e.g. 1-100x2).",
    )
    output: str = Field(..., description="Directory for rendered frames.")
    farm: str = Field(
        "mock",
        description="Render farm to submit to (see /farms for the available adapters).",
    )
    priority: int = Field(
        50, ge=0, description="Render job priority communicated to the adapter."
    )
    user: str | None = Field(
        None,
        description="Submitting user; defaults to the service account if omitted.",
    )

    @field_validator("dcc")
    @classmethod
    def _normalise_dcc(cls, value: str) -> str:
        text = value.strip().lower()
        if text not in DCC_CHOICES:
            raise ValueError(
                f"Unsupported DCC '{value}'. Choose one of: {', '.join(sorted(DCC_CHOICES))}."
            )
        return text

    @field_validator("farm")
    @classmethod
    def _normalise_farm(cls, value: str) -> str:
        text = value.strip().lower()
        if text not in FARM_ADAPTERS:
            raise ValueError(
                f"Unknown farm '{value}'. Choose one of: {', '.join(sorted(FARM_ADAPTERS))}."
            )
        return text

    @field_validator("scene", "output", "frames", "user", mode="before")
    @classmethod
    def _strip_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("Value cannot be empty.")
        return text


class RenderJobResponse(BaseModel):
    """Response payload describing the outcome of a render submission."""

    job_id: str = Field(
        ..., description="Identifier returned by the render farm (if any)."
    )
    status: str = Field(
        ..., description="Submission status reported by the render farm."
    )
    farm_type: str = Field(
        ..., description="Render farm adapter that processed the submission."
    )
    message: str | None = Field(
        None,
        description="Optional detail returned by the adapter (for example not implemented notices).",
    )


class RenderSubmissionService:
    """Submit render jobs using the shared adapter registry."""

    def __init__(self, adapters: Mapping[str, RenderAdapter] | None = None) -> None:
        self._adapters = dict(adapters or FARM_ADAPTERS)

    def list_farms(self) -> list[FarmInfo]:
        entries: list[FarmInfo] = []
        for name in sorted(self._adapters):
            description = FARM_DESCRIPTIONS.get(
                name, f"Render farm adapter registered as '{name}'."
            )
            entries.append(FarmInfo(name=name, description=description))
        return entries

    def submit_job(self, request: RenderJobRequest) -> SubmissionResult:
        adapter = self._adapters.get(request.farm)
        if adapter is None:
            raise RenderSubmissionError(f"Unknown render farm '{request.farm}'.")
        resolved_user = request.user or getpass.getuser()
        return adapter(
            scene=request.scene,
            frames=request.frames,
            output=request.output,
            dcc=request.dcc,
            priority=request.priority,
            user=resolved_user,
        )


def get_render_service() -> (
    RenderSubmissionService
):  # pragma: no cover - runtime wiring
    return RenderSubmissionService()


app = FastAPI(title="OnePiece Render Service", version="1.0.0")


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    logger.info(
        "render.api.request.start", method=request.method, path=request.url.path
    )
    response = await call_next(request)
    logger.info(
        "render.api.request.complete",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    return response


@app.get("/")
def root() -> Mapping[str, str]:
    return {"message": "OnePiece Render API is running"}


@app.get("/health")
def health() -> Mapping[str, str]:
    return {"status": "ok"}


@app.get("/farms", response_model=FarmsResponse)
def farms(
    service: RenderSubmissionService = Depends(get_render_service),
) -> FarmsResponse:
    entries = service.list_farms()
    return FarmsResponse(farms=entries)


@app.post("/jobs")
async def create_job(
    request: RenderJobRequest,
    service: RenderSubmissionService = Depends(get_render_service),
) -> JSONResponse:
    logger.info(
        "render.api.submit.start",
        dcc=request.dcc,
        scene=request.scene,
        frames=request.frames,
        output=request.output,
        farm=request.farm,
        priority=request.priority,
        user=request.user,
    )
    try:
        result = service.submit_job(request)
    except RenderSubmissionError as exc:
        logger.warning(
            "render.api.submit.failed",
            farm=request.farm,
            scene=request.scene,
            error=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception(
            "render.api.submit.error",
            farm=request.farm,
            scene=request.scene,
        )
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while submitting render job.",
        ) from exc

    payload = RenderJobResponse(
        job_id=result.get("job_id", ""),
        status=result.get("status", "unknown"),
        farm_type=result.get("farm_type", request.farm),
        message=result.get("message"),
    )

    status_code = 201
    if payload.status == "not_implemented":
        status_code = 501

    logger.info(
        "render.api.submit.complete",
        farm=payload.farm_type,
        status=payload.status,
        job_id=payload.job_id,
    )

    return JSONResponse(status_code=status_code, content=payload.model_dump())
