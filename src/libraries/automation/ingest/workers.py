"""Worker sizing and execution helpers for ingest."""

from __future__ import annotations

import asyncio
import concurrent.futures
import math
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Sequence

if TYPE_CHECKING:
    from logging import Logger

    from .checkpoint import UploadCheckpointStore
    from .service import MediaIngestService, _UploadJob, _UploadResult


def apply_worker_tuning(
    service: "MediaIngestService",
    jobs: Sequence["_UploadJob"],
    *,
    logger: "Logger",
    bytes_target: int,
    files_target: int,
) -> None:
    """Analyse *jobs* and update the configured worker count on *service*."""

    resolved, analysis = determine_worker_count(
        jobs,
        configured_cap=service._configured_max_workers,
        auto_tune_workers=service.auto_tune_workers,
        bytes_target=bytes_target,
        files_target=files_target,
        logger=logger,
    )
    service._worker_analysis = analysis
    service._resolved_worker_count = resolved
    service.max_workers = resolved


def determine_worker_count(
    jobs: Sequence["_UploadJob"],
    *,
    configured_cap: int,
    auto_tune_workers: bool,
    bytes_target: int,
    files_target: int,
    logger: "Logger",
) -> tuple[int, dict[str, object]]:
    """Return the worker count and telemetry for the provided *jobs*."""

    cap = configured_cap
    total_jobs = len(jobs)
    total_bytes = sum(job.size for job in jobs)
    largest_job = max((job.size for job in jobs), default=0)
    target_by_files: int | None = None
    target_by_bytes: int | None = None
    auto_tuned = False

    if total_jobs == 0:
        resolved = cap
    elif cap <= 1:
        resolved = 1
    elif not auto_tune_workers:
        resolved = cap
    else:
        target_by_files = max(1, math.ceil(total_jobs / files_target))
        target_by_bytes = max(1, math.ceil(total_bytes / bytes_target))
        target = max(target_by_files, target_by_bytes)
        resolved = max(1, min(cap, min(total_jobs, target)))
        auto_tuned = True

    analysis: dict[str, object] = {
        "configured_cap": cap,
        "resolved_workers": resolved,
        "total_jobs": total_jobs,
        "total_bytes": total_bytes,
        "largest_job": largest_job,
        "auto_tuned": auto_tuned,
    }
    if target_by_files is not None:
        analysis["target_by_files"] = target_by_files
    if target_by_bytes is not None:
        analysis["target_by_bytes"] = target_by_bytes

    logger.info("ingest.worker_count_resolved", **analysis)

    return resolved, analysis


def execute_uploads(
    service: "MediaIngestService",
    jobs: Sequence["_UploadJob"],
    checkpoint_store: "UploadCheckpointStore" | None,
) -> list["_UploadResult"] | Awaitable[list["_UploadResult"]]:
    """Execute *jobs* using the concurrency configuration on *service*."""

    if not jobs:
        return []

    if service.use_asyncio:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(service._run_asyncio_jobs(jobs, checkpoint_store))
        else:
            return service._run_asyncio_jobs(jobs, checkpoint_store)

    if service.max_workers <= 1:
        return [service._process_job(job, checkpoint_store) for job in jobs]

    results: dict[Path, "_UploadResult"] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=service.max_workers) as executor:
        future_to_job = {
            executor.submit(service._process_job, job, checkpoint_store): job
            for job in jobs
        }
        for future in concurrent.futures.as_completed(future_to_job):
            job = future_to_job[future]
            results[job.path] = future.result()

    return [results[job.path] for job in jobs]


__all__ = [
    "apply_worker_tuning",
    "determine_worker_count",
    "execute_uploads",
]
