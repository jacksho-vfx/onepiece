"""Deadline submission helpers for optimization jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from libraries.pipeline.optimize.config import DeadlineConfig


@dataclass(frozen=True)
class DeadlineJob:
    variant: str
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
    asset_id: str,
    asset_dir: Path,
    variant: str,
    project_root: Path,
    config: DeadlineConfig,
) -> DeadlineJob:
    job_dir = asset_dir / "deadline_jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    job_info: dict[str, Any] = {
        "Name": f"optimize-{asset_id}-{variant}",
        "Plugin": "CommandLine",
        "Frames": "0",
    }
    if config.pool:
        job_info["Pool"] = config.pool
    if config.group:
        job_info["Group"] = config.group
    if config.priority is not None:
        job_info["Priority"] = str(config.priority)
    job_info.update({str(key): str(value) for key, value in config.extra_info.items()})
    python_executable = "python"
    arguments = (
        f"-m apps.onepiece optimize run {asset_id} --variant {variant} "
        f"--project-root {project_root.as_posix()}"
    )
    plugin_info = {
        "Arguments": arguments,
        "Executable": python_executable,
        "WorkingDirectory": str(project_root),
    }
    job_info_path = job_dir / f"optimize_{variant}_job_info.job"
    plugin_info_path = job_dir / f"optimize_{variant}_plugin_info.job"
    _write_job_info(job_info_path, job_info)
    _write_plugin_info(plugin_info_path, plugin_info)
    return DeadlineJob(
        variant=variant,
        job_info_path=job_info_path,
        plugin_info_path=plugin_info_path,
        job_info=job_info,
        plugin_info=plugin_info,
    )


def submit_deadline_job(job: DeadlineJob) -> str:
    from libraries.pipeline.deadline_submit import submit_deadline_payload

    payload = {"JobInfo": job.job_info, "PluginInfo": job.plugin_info}
    return cast(str, submit_deadline_payload(payload))
