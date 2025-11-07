"""Review dashboard facade."""

from __future__ import annotations

from typing import Any, Iterable

import structlog

from libraries.automation.review.dailies import DailiesClip, fetch_playlist_versions
from libraries.integrations.shotgrid.api import ShotGridError

from ... import review as review_module

logger = structlog.get_logger(__name__)

__all__ = ["ReviewDashboardFacade", "get_review_dashboard_facade"]


class ReviewDashboardFacade:
    """Summarise review playlist activity across projects."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client or review_module.get_shotgrid_client()

    def summarise_projects(self, project_names: Iterable[str]) -> dict[str, Any]:
        project_summaries: list[dict[str, Any]] = []
        total_playlists = 0
        total_clips = 0
        total_shots = 0
        total_duration = 0.0

        for project in project_names:
            try:
                playlists = review_module._list_project_playlists(  # noqa: SLF001
                    self._client, project
                )
            except ShotGridError as exc:
                logger.warning(
                    "dashboard.review.playlists_failed",
                    project=project,
                    error=str(exc),
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "dashboard.review.playlists_error",
                    project=project,
                    error=str(exc),
                )
                continue

            playlists_processed = 0
            project_clips = 0
            project_shots = 0
            project_duration = 0.0

            for playlist in playlists:
                try:
                    clips: Iterable[DailiesClip] = fetch_playlist_versions(
                        self._client, project, playlist
                    )
                except ShotGridError as exc:
                    logger.warning(
                        "dashboard.review.playlist_summary_failed",
                        project=project,
                        playlist=playlist,
                        error=str(exc),
                    )
                    continue
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.warning(
                        "dashboard.review.playlist_summary_error",
                        project=project,
                        playlist=playlist,
                        error=str(exc),
                    )
                    continue

                summary = review_module._summarise_clips(clips)  # noqa: SLF001
                playlists_processed += 1
                project_clips += int(summary.get("clips", 0))
                project_shots += int(summary.get("shots", 0))
                project_duration += float(summary.get("duration_seconds", 0.0))

            total_playlists += playlists_processed
            total_clips += project_clips
            total_shots += project_shots
            total_duration += project_duration

            project_summaries.append(
                {
                    "project": project,
                    "playlists": playlists_processed,
                    "clips": project_clips,
                    "shots": project_shots,
                    "duration_seconds": project_duration,
                }
            )

        return {
            "totals": {
                "projects": len(project_summaries),
                "playlists": total_playlists,
                "clips": total_clips,
                "shots": total_shots,
                "duration_seconds": total_duration,
            },
            "projects": project_summaries,
        }


def get_review_dashboard_facade() -> ReviewDashboardFacade:  # pragma: no cover - wiring
    return ReviewDashboardFacade()
