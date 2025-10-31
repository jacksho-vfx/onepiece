"""System and configuration routes."""

from __future__ import annotations

from fastapi import APIRouter

from apps.perona.web.dashboard import dependencies
from libraries.analytics.perona.models import SettingsSummary

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    """Simple health endpoint for uptime checks."""

    return {"status": "ok"}


@router.get("/settings", response_model=SettingsSummary)
def settings_summary() -> SettingsSummary:
    """Return the resolved configuration powering the dashboard."""

    return dependencies.get_settings_summary()


@router.post("/settings/reload", response_model=SettingsSummary)
def settings_reload() -> SettingsSummary:
    """Reload engine configuration and return the updated settings summary."""

    return dependencies.reload_settings()


__all__ = ["router"]
