"""Deadline job submission helpers for ingest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from libraries.pipeline.ingest.config import DeadlineActionConfig


@dataclass(frozen=True)
class DeadlineJob:
    action: str
    job_info_path: Path
    plugin_info_path: Path
    job_info: dict[str, Any]
    plugin_info: dict[str, Any]


def _write_job_info(path: Path, job_info: dict[str, Any]) -> None:
    lines = [f"{key}={value}" for key, value in job_info.items()]
    path.write_text("\n".join(lines) + "\n")


def _write_plugin_info(path: Path, plugin_info: dict[str, Any]) -> None:
    lines = [f"{key}={value}" for key, value in plugin_info.items()]
    path.write_text("\n".join(lines) + "\n")


def build_deadline_job(
    *,
    action: str,
    asset_id: str,
    asset_dir: Path,
    payload_path: Path,
    config: DeadlineActionConfig,
) -> DeadlineJob:
    job_dir = asset_dir / "deadline_jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    job_info = {
        "Name": f"ingest-{action}-{asset_id}",
        "Plugin": config.plugin or "CommandLine",
        "Frames": "0",
    }
    if config.pool:
        job_info["Pool"] = config.pool
    if config.group:
        job_info["Group"] = config.group
    if config.priority is not None:
        job_info["Priority"] = str(config.priority)
    job_info.update({str(key): str(value) for key, value in config.extra_info.items()})
    plugin_info = {
        "Arguments": str(payload_path),
        "Executable": str(payload_path),
        "WorkingDirectory": str(payload_path.parent),
    }
    job_info_path = job_dir / f"{action}_job_info.job"
    plugin_info_path = job_dir / f"{action}_plugin_info.job"
    _write_job_info(job_info_path, job_info)
    _write_plugin_info(plugin_info_path, plugin_info)
    return DeadlineJob(
        action=action,
        job_info_path=job_info_path,
        plugin_info_path=plugin_info_path,
        job_info=job_info,
        plugin_info=plugin_info,
    )


def submit_deadline_job(job: DeadlineJob) -> str:
    from libraries.pipeline.deadline_submit import submit_deadline_payload

    payload = {"JobInfo": job.job_info, "PluginInfo": job.plugin_info}
    return cast(str, submit_deadline_payload(payload))
