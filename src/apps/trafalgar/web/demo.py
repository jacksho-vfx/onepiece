"""Demo configuration for the Trafalgar dashboard application.

This module wires the primary dashboard FastAPI app with rich sample data so
that teams can showcase the interface without connecting to production
services. It mirrors the dependency overrides used in tests but provides
realistic, studio-style payloads covering ShotGrid summaries, ingest runs,
render activity, deliveries, and review playlists.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import FastAPI

from apps.trafalgar.web import dashboard


def _utc(timestamp: str) -> str:
    """Return an ISO-8601 timestamp with an explicit UTC offset."""

    value = datetime.fromisoformat(timestamp)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


_DEMO_PROJECTS: dict[str, dict[str, Any]] = {
    "Atlas Rising": {
        "episodes": {
            "AR101": {
                "shots": 38,
                "versions": 160,
                "status_counts": {
                    "approved": 54,
                    "published": 52,
                    "in_progress": 54,
                },
            },
            "AR102": {
                "shots": 42,
                "versions": 182,
                "status_counts": {
                    "approved": 60,
                    "published": 58,
                    "review": 64,
                },
            },
            "AR103": {
                "shots": 36,
                "versions": 174,
                "status_counts": {
                    "approved": 62,
                    "published": 48,
                    "retake": 64,
                },
            },
        },
        "latest_published": [
            {
                "shot": "AR101_010",
                "version": "v045",
                "user": "M. Silva",
                "timestamp": _utc("2024-05-18T14:22:00"),
            },
            {
                "shot": "AR102_130",
                "version": "v051",
                "user": "A. Kwan",
                "timestamp": _utc("2024-05-17T19:05:00"),
            },
            {
                "shot": "AR103_080",
                "version": "v039",
                "user": "S. Novak",
                "timestamp": _utc("2024-05-16T08:42:00"),
            },
        ],
    },
    "Signal Noir": {
        "episodes": {
            "SN201": {
                "shots": 44,
                "versions": 168,
                "status_counts": {
                    "approved": 48,
                    "published": 60,
                    "review": 60,
                },
            },
            "SN202": {
                "shots": 39,
                "versions": 150,
                "status_counts": {
                    "approved": 42,
                    "published": 48,
                    "in_progress": 60,
                },
            },
        },
        "latest_published": [
            {
                "shot": "SN201_220",
                "version": "v033",
                "user": "T. Laurent",
                "timestamp": _utc("2024-05-18T05:12:00"),
            },
            {
                "shot": "SN202_040",
                "version": "v027",
                "user": "C. Patel",
                "timestamp": _utc("2024-05-17T22:18:00"),
            },
        ],
    },
}


def _enrich_projects() -> dict[str, dict[str, Any]]:
    enriched: dict[str, dict[str, Any]] = {}
    for name, data in _DEMO_PROJECTS.items():
        episodes = data["episodes"]
        status_totals: Counter[str] = Counter()
        shots_total = 0
        versions_total = 0
        for episode_data in episodes.values():
            shots_total += episode_data["shots"]
            versions_total += episode_data["versions"]
            status_totals.update(episode_data["status_counts"])

        enriched[name] = {
            "episodes": episodes,
            "shots": shots_total,
            "versions": versions_total,
            "approved_versions": status_totals.get("approved", 0),
            "status_totals": dict(sorted(status_totals.items())),
            "latest_published": list(data.get("latest_published", [])),
        }
    return enriched


_PROJECT_CACHE = _enrich_projects()


class DemoShotGridService:
    """Stub ShotGrid aggregation with curated demo payloads."""

    def __init__(self) -> None:
        self._projects = _PROJECT_CACHE
        self._cache_settings = {
            "ttl_seconds": 900,
            "max_records": 5000,
            "max_projects": 25,
        }

    @property
    def cache_settings(self) -> dict[str, int]:
        return dict(self._cache_settings)

    def configure_cache(self, **_: Any) -> None:
        """Ignore cache updates in demo mode."""

    def invalidate_cache(self) -> None:
        """No caching is performed for demo data."""

    def discover_projects(self) -> list[str]:
        return sorted(self._projects)

    def overall_status(self) -> dict[str, Any]:
        projects = self.discover_projects()
        shots = sum(project["shots"] for project in self._projects.values())
        versions = sum(project["versions"] for project in self._projects.values())
        return {"projects": len(projects), "shots": shots, "versions": versions}

    def _require_project(self, project_name: str) -> dict[str, Any]:
        try:
            return self._projects[project_name]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(project_name) from exc

    def project_summary(self, project_name: str) -> dict[str, Any]:
        project = self._require_project(project_name)
        return {
            "project": project_name,
            "episodes": len(project["episodes"]),
            "shots": project["shots"],
            "versions": project["versions"],
            "approved_versions": project["approved_versions"],
            "status_totals": dict(project["status_totals"]),
            "latest_published": list(project["latest_published"]),
        }

    def project_episode_summary(self, project_name: str) -> dict[str, Any]:
        project = self._require_project(project_name)
        episode_summaries = []
        status_totals: Counter[str] = Counter()
        for episode, data in sorted(project["episodes"].items()):
            status_counts = dict(sorted(data["status_counts"].items()))
            status_totals.update(status_counts)
            episode_summaries.append(
                {
                    "episode": episode,
                    "shots": data["shots"],
                    "versions": data["versions"],
                    "status_counts": status_counts,
                }
            )

        return {
            "project": project_name,
            "episodes": episode_summaries,
            "status_totals": dict(sorted(status_totals.items())),
        }


class DemoReconcileService:
    """Provide deterministic mismatch data for the demo dashboard."""

    _MISMATCHES = [
        {
            "type": "filesystem_missing",
            "path": "//render/atlas_rising/AR101_090/v012/beauty.exr",
            "shot": "AR101_090",
        },
        {
            "type": "s3_version_drift",
            "path": "s3://studio-prod/atlas_rising/AR103_020/v010/comp.mov",
            "shot": "AR103_020",
        },
        {
            "type": "metadata_mismatch",
            "key": "Signal Noir/SN202_040/v018",
            "shot": "SN202_040",
        },
    ]

    def list_errors(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._MISMATCHES]

    def summarise_errors(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for mismatch in self._MISMATCHES:
            mismatch_type = mismatch.get("type", "unknown")
            path = mismatch.get("path") or mismatch.get("key") or ""
            group = grouped.setdefault(
                (mismatch_type, path),
                {"type": mismatch_type, "path": path, "count": 0, "shots": set()},
            )
            group["count"] += 1
            shot = mismatch.get("shot")
            if shot:
                group["shots"].add(str(shot))

        summary: list[dict[str, Any]] = []
        for (_, _), payload in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1])
        ):
            summary.append(
                {
                    "type": payload["type"],
                    "path": payload["path"],
                    "count": payload["count"],
                    "shots": sorted(payload["shots"]),
                }
            )
        return summary


class DemoIngestFacade:
    """Return a handcrafted ingest summary for the demo interface."""

    def summarise_recent_runs(self, limit: int = 10) -> dict[str, Any]:
        return {
            "counts": {
                "total": 6,
                "successful": 4,
                "failed": 1,
                "running": 1,
            },
            "last_success_at": _utc("2024-05-20T08:30:00"),
            "failure_streak": 1,
            "sample_window": limit,
        }


class DemoRenderFacade:
    """Surface render farm activity without hitting live services."""

    async def summarise_jobs(self) -> dict[str, Any]:
        return {
            "jobs": 14,
            "by_status": {
                "queued": 3,
                "running": 2,
                "completed": 9,
            },
            "by_farm": {
                "onyx": 6,
                "ember": 5,
                "mock": 3,
            },
        }


class DemoReviewFacade:
    """Expose playlist activity summarised from canned data."""

    _SUMMARY = {
        "Atlas Rising": {
            "playlists": 5,
            "clips": 48,
            "shots": 32,
            "duration_seconds": 12600.0,
        },
        "Signal Noir": {
            "playlists": 4,
            "clips": 36,
            "shots": 24,
            "duration_seconds": 9600.0,
        },
    }

    def summarise_projects(self, project_names: Iterable[str]) -> dict[str, Any]:
        projects = []
        totals: dict[str, float] = {
            "playlists": 0.0,
            "clips": 0.0,
            "shots": 0.0,
            "duration_seconds": 0.0,
        }
        seen: set[str] = set()
        for name in project_names:
            data = self._SUMMARY.get(name)
            if not data:
                continue
            seen.add(name)
            projects.append({"project": name, **data})
            totals["playlists"] += data["playlists"]
            totals["clips"] += data["clips"]
            totals["shots"] += data["shots"]
            totals["duration_seconds"] += data["duration_seconds"]

        return {
            "totals": {
                "projects": len(seen),
                "playlists": totals["playlists"],
                "clips": totals["clips"],
                "shots": totals["shots"],
                "duration_seconds": float(totals["duration_seconds"]),
            },
            "projects": projects,
        }


class DemoDeliveryService:
    """Serve static delivery payloads for demo exploration."""

    _DELIVERIES: dict[str, list[dict[str, Any]]] = {
        "Atlas Rising": [
            {
                "delivery_id": "atlas-rising-daily-0520",
                "name": "Atlas Rising – Sequence 101 daily",
                "created_at": _utc("2024-05-20T09:15:00"),
                "items": [
                    {
                        "path": "AR101/AR101_090/v012/AR101_090_v012.mov",
                        "size": 734003200,
                        "checksum": "b0e1c6d3",
                    },
                    {
                        "path": "AR101/AR101_090/v012/AR101_090_v012.wav",
                        "size": 12582912,
                        "checksum": "1a45f0b2",
                    },
                ],
            },
            {
                "delivery_id": "atlas-rising-finals-0517",
                "name": "Atlas Rising finals batch",
                "created_at": _utc("2024-05-17T18:40:00"),
                "items": [
                    {
                        "path": "finals/AR103_080/v020/AR103_080_v020.exr",
                        "size": 157286400,
                        "checksum": "7cd4a210",
                    }
                ],
            },
        ],
        "Signal Noir": [
            {
                "delivery_id": "signal-noir-daily-0519",
                "name": "Signal Noir nightly",
                "created_at": _utc("2024-05-19T23:05:00"),
                "items": [
                    {
                        "path": "SN201/SN201_220/v015/SN201_220_v015.mov",
                        "size": 618659840,
                        "checksum": "5f91bb7c",
                    }
                ],
            }
        ],
    }

    _MANIFESTS: dict[str, dict[str, Any]] = {
        "atlas-rising-daily-0520": {
            "files": [
                {
                    "path": "AR101/AR101_090/v012/AR101_090_v012.mov",
                    "size": 734003200,
                    "checksum": "b0e1c6d3",
                    "codec": "ProRes 4444",
                },
                {
                    "path": "AR101/AR101_090/v012/AR101_090_v012.wav",
                    "size": 12582912,
                    "checksum": "1a45f0b2",
                    "channels": 6,
                },
            ]
        },
        "atlas-rising-finals-0517": {
            "files": [
                {
                    "path": "finals/AR103_080/v020/AR103_080_v020.exr",
                    "size": 157286400,
                    "checksum": "7cd4a210",
                    "bit_depth": 16,
                }
            ]
        },
        "signal-noir-daily-0519": {
            "files": [
                {
                    "path": "SN201/SN201_220/v015/SN201_220_v015.mov",
                    "size": 618659840,
                    "checksum": "5f91bb7c",
                    "codec": "DNxHR HQX",
                }
            ]
        },
    }

    def list_deliveries(self, project_name: str) -> list[dict[str, Any]]:
        deliveries = self._DELIVERIES.get(project_name)
        if not deliveries:
            return []

        payload: list[dict[str, Any]] = []
        for entry in deliveries:
            record = dict(entry)
            items = record.get("items", [])
            record["file_count"] = len(items)
            payload.append(record)
        return payload

    def get_delivery_manifest(
        self, project_name: str, identifier: str
    ) -> dict[str, Any]:
        deliveries = self._DELIVERIES.get(project_name)
        if not deliveries:
            raise KeyError(identifier)
        identifier = identifier.strip()
        if identifier in self._MANIFESTS:
            return dict(self._MANIFESTS[identifier])
        for entry in deliveries:
            if entry.get("delivery_id") == identifier:
                manifest = self._MANIFESTS.get(identifier)
                if manifest:
                    return dict(manifest)
        raise KeyError(identifier)


def _apply_demo_overrides(app: FastAPI) -> FastAPI:
    app.dependency_overrides.clear()

    shotgrid = DemoShotGridService()
    app.dependency_overrides[dashboard.get_shotgrid_service] = lambda: shotgrid
    app.dependency_overrides[dashboard.get_reconcile_service] = (
        lambda: DemoReconcileService()
    )
    app.dependency_overrides[dashboard.get_ingest_dashboard_facade] = (
        lambda: DemoIngestFacade()
    )
    app.dependency_overrides[dashboard.get_render_dashboard_facade] = (
        lambda: DemoRenderFacade()
    )
    app.dependency_overrides[dashboard.get_review_dashboard_facade] = (
        lambda: DemoReviewFacade()
    )
    app.dependency_overrides[dashboard.get_delivery_service] = (
        lambda: DemoDeliveryService()
    )

    app.title = "OnePiece Dashboard (Demo)"
    app.state.dashboard_demo = True
    cache_settings = shotgrid.cache_settings
    app.state.dashboard_cache_ttl = cache_settings["ttl_seconds"]
    app.state.dashboard_cache_max_records = cache_settings["max_records"]
    app.state.dashboard_cache_max_projects = cache_settings["max_projects"]
    return app


app: FastAPI = _apply_demo_overrides(dashboard.app)
