"""Shared helpers for Deadline job payload construction."""

from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

DeadlineJobKind = Literal["job", "test", "preset", "rnd"]


def build_command_job_payload(
    *,
    name: str,
    executable: str,
    job_kind: DeadlineJobKind,
    arguments: Sequence[str] | str | None = None,
    user: str | None = None,
    priority: int | None = None,
    pool: str | None = None,
    group: str | None = None,
    department: str | None = None,
    comment: str | None = None,
    environment: Mapping[str, str] | None = None,
    extra_job_info: Mapping[str, Any] | None = None,
    extra_plugin_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a CommandLine plugin payload for common Deadline task types."""

    job_info: dict[str, Any] = {
        "Name": name,
        "Plugin": "CommandLine",
        "BatchName": job_kind,
        "ExtraInfoKeyValue0": f"job_kind={job_kind}",
    }

    if user:
        job_info["UserName"] = user
    if priority is not None:
        job_info["Priority"] = priority
    if pool:
        job_info["Pool"] = pool
    if group:
        job_info["Group"] = group
    if department:
        job_info["Department"] = department
    if comment:
        job_info["Comment"] = comment
    if environment:
        for index, (key, value) in enumerate(sorted(environment.items())):
            job_info[f"EnvironmentKeyValue{index}"] = f"{key}={value}"

    if extra_job_info:
        job_info.update(extra_job_info)

    plugin_info: dict[str, Any] = {"Executable": executable}
    formatted_arguments = _format_arguments(arguments)
    if formatted_arguments:
        plugin_info["Arguments"] = formatted_arguments
    if extra_plugin_info:
        plugin_info.update(extra_plugin_info)

    return {"JobInfo": job_info, "PluginInfo": plugin_info}


def _format_arguments(arguments: Sequence[str] | str | None) -> str | None:
    if arguments is None:
        return None
    if isinstance(arguments, str):
        return arguments
    return " ".join(str(arg) for arg in arguments)


__all__ = ["DeadlineJobKind", "build_command_job_payload"]
