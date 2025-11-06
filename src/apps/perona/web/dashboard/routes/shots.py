"""Shot lifecycle and production routes."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Sequence

from fastapi import APIRouter, Depends, Query

from apps.perona.web.dashboard import dependencies
from libraries.analytics.perona.engine.engine import PeronaEngine
from libraries.analytics.perona.engine.models import ShotLifecycle
from libraries.analytics.perona.models import Shot
from libraries.analytics.perona.models import Sequence as PeronaSequence
from libraries.analytics.perona.models import sequences_from_lifecycles

router = APIRouter(prefix="/shots", tags=["shots"])


def _lifecycle_date_bounds(lifecycle: ShotLifecycle) -> tuple[datetime, datetime]:
    """Return the earliest start and latest activity timestamps for a lifecycle."""

    starts = [stage.started_at for stage in lifecycle.stages]
    now = datetime.utcnow()
    ends = [stage.completed_at or now for stage in lifecycle.stages]
    return min(starts), max(ends)


def filter_lifecycles(
    lifecycles: Sequence[ShotLifecycle],
    sequence: str | None,
    artist: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
) -> list[ShotLifecycle]:
    """Filter lifecycles using the supplied query parameters."""

    artist_lower = artist.lower() if artist else None

    filtered: list[ShotLifecycle] = []
    for lifecycle in lifecycles:
        if sequence and lifecycle.sequence != sequence:
            continue

        if artist_lower:
            matches_artist = any(
                isinstance(stage.metrics.get("artist"), str)
                and stage.metrics["artist"].lower() == artist_lower
                for stage in lifecycle.stages
            )
            if not matches_artist:
                continue

        if start_date or end_date:
            first_activity, last_activity = _lifecycle_date_bounds(lifecycle)
            if start_date and last_activity < start_date:
                continue
            if end_date and first_activity > end_date:
                continue

        filtered.append(lifecycle)

    return filtered


def compute_shots_summary(
    lifecycles: Sequence[ShotLifecycle],
) -> dict[str, Any]:
    """Return aggregated production status for monitored shots."""

    lifecycles = list(lifecycles)

    total = len(lifecycles)
    completed = sum(
        1
        for lifecycle in lifecycles
        if all(stage.completed_at is not None for stage in lifecycle.stages)
    )

    by_stage = Counter(lifecycle.current_stage for lifecycle in lifecycles)
    by_sequence = Counter(lifecycle.sequence for lifecycle in lifecycles)

    active_shots: list[dict[str, Any]] = []
    for lifecycle in lifecycles:
        if all(stage.completed_at is not None for stage in lifecycle.stages):
            continue

        current_stage_name = lifecycle.current_stage
        stage_details = next(
            (stage for stage in lifecycle.stages if stage.name == current_stage_name),
            None,
        )
        active_shots.append(
            {
                "sequence": lifecycle.sequence,
                "shot_id": lifecycle.shot_id,
                "current_stage": current_stage_name,
                "stage_started_at": stage_details.started_at if stage_details else None,
                "stage_completed_at": (
                    stage_details.completed_at if stage_details else None
                ),
                "stage_metrics": (
                    dict(stage_details.metrics) if stage_details is not None else {}
                ),
            }
        )

    active_shots.sort(key=lambda item: (item["sequence"], item["shot_id"]))

    return {
        "total": total,
        "completed": completed,
        "active": max(total - completed, 0),
        "by_sequence": [
            {"name": name, "shots": count}
            for name, count in sorted(by_sequence.items())
        ],
        "by_stage": [
            {"name": name, "shots": count} for name, count in by_stage.most_common()
        ],
        "active_shots": active_shots,
    }


@router.get("/lifecycle", response_model=list[Shot])
def shots_lifecycle(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> list[Shot]:
    """Return lifecycle timelines for key monitored shots."""

    lifecycles = filter_lifecycles(
        engine.shot_lifecycle(), sequence, artist, start_date, end_date
    )
    return [Shot.from_entity(item) for item in lifecycles]


@router.get("/sequences", response_model=list[PeronaSequence])
def shot_sequences(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> list[PeronaSequence]:
    """Return monitored shots grouped by sequence."""

    lifecycles = filter_lifecycles(
        engine.shot_lifecycle(), sequence, artist, start_date, end_date
    )
    sequences = sequences_from_lifecycles(lifecycles)
    return list(sequences)


@router.get("")
def shots_summary(
    sequence: str | None = Query(None),
    artist: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    engine: PeronaEngine = Depends(dependencies.get_engine),
) -> dict[str, Any]:
    """Return aggregated production status for monitored shots."""

    lifecycles = filter_lifecycles(
        engine.shot_lifecycle(), sequence, artist, start_date, end_date
    )
    return compute_shots_summary(lifecycles)


__all__ = ["router", "compute_shots_summary", "filter_lifecycles"]
