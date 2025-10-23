"""Comparison helpers for reconciliation workflows."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, Iterable, List, Optional

import structlog

log = structlog.get_logger(__name__)

Record = Dict[str, str]
ProgressCallback = Callable[[int], None]


def _build_index(records: Iterable[Record]) -> Dict[str, List[Record]]:
    index: Dict[str, List[Record]] = defaultdict(list)
    for record in records:
        shot = record.get("shot")
        if not shot:
            continue
        index[shot.lower()].append(record)
    return index


def collect_shots(
    shotgrid: Iterable[Record],
    filesystem: Iterable[Record],
    s3: Optional[Iterable[Record]] = None,
) -> List[str]:
    shots = set()
    for record in shotgrid:
        if record.get("shot"):
            shots.add(record["shot"].lower())
    for record in filesystem:
        if record.get("shot"):
            shots.add(record["shot"].lower())
    if s3:
        for record in s3:
            if record.get("shot"):
                shots.add(record["shot"].lower())
    return sorted(shots)


def _normalise_versions(
    records: Iterable[Record], *, field: str = "version"
) -> Dict[str, List[str]]:
    index = defaultdict(list)
    for record in records:
        shot = record.get("shot")
        version = record.get(field)
        if not shot or not version:
            continue
        if isinstance(version, int):
            value = f"v{version:03d}"
        else:
            value = str(version)
        index[shot.lower()].append(value.lower())
    return index


def compare_datasets(
    shotgrid: Iterable[Record],
    filesystem: Iterable[Record],
    s3: Optional[Iterable[Record]] = None,
    *,
    shots: Optional[Iterable[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Record]:
    """Return a list describing discrepancies between datasets."""

    fs_index = _build_index(filesystem)
    s3_index = _build_index(s3 or [])

    sg_versions = _normalise_versions(shotgrid, field="version_number")
    if not any(sg_versions.values()):
        sg_versions = _normalise_versions(shotgrid)
    fs_versions = _normalise_versions(filesystem)
    s3_versions = _normalise_versions(s3 or [])

    shot_list = (
        list(shots) if shots is not None else collect_shots(shotgrid, filesystem, s3)
    )

    mismatches: List[Record] = []
    for shot in shot_list:
        if progress_callback:
            progress_callback(1)

        fs_records = fs_index.get(shot, [])
        s3_records = s3_index.get(shot, [])

        sg_versions_for_shot = set(sg_versions.get(shot, []))
        fs_versions_for_shot = set(fs_versions.get(shot, []))
        s3_versions_for_shot = set(s3_versions.get(shot, []))

        for missing_version in sg_versions_for_shot - fs_versions_for_shot:
            mismatches.append(
                {
                    "type": "missing_in_fs",
                    "shot": shot,
                    "expected": missing_version,
                    "source": "shotgrid",
                }
            )

        if s3 is not None:
            for missing_version in sg_versions_for_shot - s3_versions_for_shot:
                mismatches.append(
                    {
                        "type": "missing_in_s3",
                        "shot": shot,
                        "expected": missing_version,
                        "source": "shotgrid",
                    }
                )

        for orphan_version in fs_versions_for_shot - sg_versions_for_shot:
            path = fs_records[0].get("path") if fs_records else None
            mismatches.append(
                {
                    "type": "orphan_in_fs",
                    "shot": shot,
                    "found": orphan_version,
                    "path": path or "",
                    "source": "filesystem",
                }
            )

        if s3 is not None:
            for orphan_version in s3_versions_for_shot - sg_versions_for_shot:
                key = s3_records[0].get("key") if s3_records else None
                mismatches.append(
                    {
                        "type": "orphan_in_s3",
                        "shot": shot,
                        "found": orphan_version,
                        "key": key or "",
                        "source": "s3",
                    }
                )

        if sg_versions_for_shot and fs_versions_for_shot:
            sg_latest = max(sg_versions_for_shot)
            fs_latest = max(fs_versions_for_shot)
            if sg_latest != fs_latest:
                mismatches.append(
                    {
                        "type": "version_mismatch",
                        "shot": shot,
                        "expected": sg_latest,
                        "found": fs_latest,
                    }
                )

    log.info(
        "reconcile.compare.complete",
        shots=len(shot_list),
        mismatches=len(mismatches),
    )
    return mismatches
