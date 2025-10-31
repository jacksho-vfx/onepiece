"""Wrangler-related API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from apps.perona.web import wrangler
from apps.perona.web.dashboard import dependencies

router = APIRouter(prefix="/wrangler", tags=["wrangler"])


@router.get("/scripts", response_model=list[wrangler.WranglerScriptMetadata])
def list_wrangler_scripts() -> Any:
    """Return metadata for all registered Wrangler scripts."""

    return dependencies.list_wrangler_scripts()


@router.post(
    "/scripts/{script_id}",
    response_model=wrangler.WranglerScriptResult,
    status_code=status.HTTP_200_OK,
)
async def execute_wrangler_script(script_id: str) -> wrangler.WranglerScriptResult:
    """Execute a registered Wrangler script and return a structured result."""

    try:
        return await wrangler.execute_script(script_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown Wrangler script."
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive catch
        return wrangler.WranglerScriptResult(
            script_id=script_id, status="error", message=str(exc)
        )


__all__ = ["router"]
