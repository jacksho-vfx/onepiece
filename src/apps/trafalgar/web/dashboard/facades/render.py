"""Render dashboard facade."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from ...render import RenderSubmissionService, get_render_service

__all__ = ["RenderDashboardFacade", "get_render_dashboard_facade"]


class RenderDashboardFacade:
    """Aggregate render job metrics for dashboard consumption."""

    def __init__(self, service: RenderSubmissionService | None = None) -> None:
        self._service = service or get_render_service()

    async def summarise_jobs(self) -> dict[str, Any]:
        jobs = await asyncio.to_thread(self._service.list_jobs)
        status_counts: Counter[str] = Counter()
        farm_counts: Counter[str] = Counter()
        for job in jobs:
            status_counts[str(job.status).lower()] += 1
            farm_counts[str(job.farm)] += 1
        return {
            "jobs": len(jobs),
            "by_status": dict(sorted(status_counts.items())),
            "by_farm": dict(sorted(farm_counts.items())),
        }


def get_render_dashboard_facade() -> RenderDashboardFacade:  # pragma: no cover - wiring
    return RenderDashboardFacade()
