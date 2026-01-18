"""Deadline command-line client implementation."""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .deadline_errors import (
    DeadlineAuthenticationError,
    DeadlineError,
    DeadlineResponseError,
    DeadlineUnavailableError,
    DeadlineValidationError,
)

_JOB_ID_PATTERN = re.compile(r"JobID=(?P<job_id>\S+)")


@dataclass
class DeadlineCommandClient:
    """Deadline client that shells out to the deadlinecommand utility."""

    base_url: str = "deadlinecommand"
    command: str = "deadlinecommand"
    env: Mapping[str, str] | None = None

    def _run_command(self, args: Sequence[str]) -> str:
        try:
            result = subprocess.run(
                list(args),
                check=False,
                capture_output=True,
                text=True,
                env=self.env,
            )
        except FileNotFoundError as exc:  # pragma: no cover - defensive
            raise DeadlineUnavailableError(
                "deadlinecommand executable not found."
            ) from exc
        except OSError as exc:  # pragma: no cover - defensive
            raise DeadlineUnavailableError("Failed to launch deadlinecommand.") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise _command_error(message)

        return result.stdout.strip()

    def submit_job(self, payload: Mapping[str, Any]) -> Any:
        """Submit a job payload using deadlinecommand."""

        job_info = payload.get("JobInfo")
        plugin_info = payload.get("PluginInfo")
        if not isinstance(job_info, Mapping) or not isinstance(plugin_info, Mapping):
            raise DeadlineValidationError(
                "Deadline payload must include JobInfo and PluginInfo mappings."
            )

        with tempfile.TemporaryDirectory(prefix="deadline_submit_") as temp_dir:
            temp_path = Path(temp_dir)
            job_path = temp_path / "job_info.job"
            plugin_path = temp_path / "plugin_info.job"

            job_path.write_text(_format_job_info(job_info), encoding="utf-8")
            plugin_path.write_text(_format_job_info(plugin_info), encoding="utf-8")

            output = self._run_command([self.command, str(job_path), str(plugin_path)])

        job_id = _parse_job_id(output)
        if not job_id:
            raise DeadlineResponseError("Deadline did not return a job identifier.")

        return {"jobId": job_id, "status": "submitted", "message": output}

    def get_job(self, job_id: str) -> Any:
        """Return metadata for the Deadline job identified by ``job_id``."""

        output = self._run_command([self.command, "-GetJob", job_id])
        payload = _parse_key_value_output(output)
        if "JobID" not in payload and "jobId" not in payload:
            payload["JobID"] = job_id
        return payload

    def delete_job(self, job_id: str) -> Any:
        """Request cancellation of the Deadline job identified by ``job_id``."""

        output = self._run_command([self.command, "-DeleteJob", job_id])
        return {"status": "cancelled", "message": output}

    def get_limits(self) -> Any:
        """Return adapter limits advertised by Deadline."""

        output = self._run_command([self.command, "-GetLimits"])
        return _parse_key_value_output(output)


def _parse_job_id(output: str) -> str | None:
    for line in output.splitlines():
        match = _JOB_ID_PATTERN.search(line)
        if match:
            return match.group("job_id")
    return output.strip() or None


def _parse_key_value_output(output: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        payload[key] = value.strip()
    return payload


def _format_job_info(info: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for key, value in info.items():
        if value is None:
            continue
        lines.append(f"{key}={value}")
    return "\n".join(lines)


def _command_error(message: str) -> DeadlineError:
    lower = message.lower()
    if any(token in lower for token in ("auth", "credential", "permission")):
        return DeadlineAuthenticationError(message or "Deadline authentication failed")
    if any(token in lower for token in ("connect", "unreachable", "timeout")):
        return DeadlineUnavailableError(message or "Deadline is unavailable")
    if any(token in lower for token in ("invalid", "failed", "rejected", "error")):
        return DeadlineValidationError(message or "Deadline rejected the job payload")
    return DeadlineUnavailableError(message or "Deadline is unavailable")


__all__ = ["DeadlineCommandClient"]
