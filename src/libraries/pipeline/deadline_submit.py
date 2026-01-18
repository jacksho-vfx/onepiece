"""Shared Deadline submission helpers for pipeline workflows."""

from __future__ import annotations

from typing import Any, Mapping, cast

from libraries.automation.render.config import get_adapter_setting
from libraries.automation.render.deadline_api import DeadlineClient
from libraries.automation.render.deadline_command import DeadlineCommandClient
from libraries.automation.render.deadline_errors import DeadlineResponseError

DEFAULT_BASE_URL = "http://localhost:8082"


def _build_base_url() -> str:
    url_override = cast(str | None, get_adapter_setting("deadline", "url"))
    if url_override:
        return url_override.rstrip("/")

    host = cast(str | None, get_adapter_setting("deadline", "host"))
    if host:
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"http://{host}".rstrip("/")

    return DEFAULT_BASE_URL


def _build_deadline_command() -> str | None:
    command = cast(str | None, get_adapter_setting("deadline", "command"))
    if command:
        return command
    use_command = cast(str | None, get_adapter_setting("deadline", "use_command"))
    if use_command and use_command.strip().lower() in {"1", "true", "yes", "on"}:
        return "deadlinecommand"
    return None


def _get_client() -> DeadlineClient | DeadlineCommandClient:
    command = _build_deadline_command()
    if command:
        return DeadlineCommandClient(command=command)

    username = cast(str | None, get_adapter_setting("deadline", "username"))
    password = cast(str | None, get_adapter_setting("deadline", "password"))

    return DeadlineClient(
        base_url=_build_base_url(),
        username=username,
        password=password,
    )


def submit_deadline_payload(payload: Mapping[str, Any]) -> str:
    client = _get_client()
    response = client.submit_job(payload)
    if not isinstance(response, Mapping):
        raise DeadlineResponseError("Deadline returned unexpected job payload.")

    job_id = str(
        response.get("jobId")
        or response.get("JobID")
        or response.get("Id")
        or response.get("id")
        or ""
    )
    if not job_id or job_id == "None":
        raise DeadlineResponseError("Deadline did not return a job identifier.")
    return job_id


__all__ = ["submit_deadline_payload"]
