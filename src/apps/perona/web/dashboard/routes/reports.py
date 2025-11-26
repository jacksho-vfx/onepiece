"""Routes exposing dashboard reports and exports."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from apps.perona.web.dashboard import dependencies
from apps.perona.web.dashboard import reports as report_utils
from libraries.analytics.perona.engine.engine import PeronaEngine

router = APIRouter(tags=["reports"])


@router.get("/dashboard/summary")
def dashboard_summary(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None, alias="to"),
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> Any:
    """Return the aggregated data backing the refreshed dashboard UI."""

    return report_utils.build_daily_summary(engine, start_time=from_, end_time=to)


@router.get("/reports/daily")
def daily_report(
    format: str = Query("csv"),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None, alias="to"),
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> StreamingResponse:
    """Generate a downloadable daily summary report in CSV or PDF format."""

    summary = report_utils.build_daily_summary(engine, start_time=from_, end_time=to)
    fmt = format.lower()
    if fmt == "csv":
        payload = report_utils.render_daily_csv(summary)
        media_type = "text/csv"
        extension = "csv"
    elif fmt == "pdf":
        payload = report_utils.render_daily_pdf(summary)
        media_type = "application/pdf"
        extension = "pdf"
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported format. Use 'csv' or 'pdf'.",
        )

    date_tag = summary["generated_at"].split("T", 1)[0]
    filename = f"perona_daily_summary_{date_tag}.{extension}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        iter([payload]),
        media_type=media_type,
        headers=headers,
    )


__all__ = ["router"]
