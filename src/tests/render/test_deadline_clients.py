"""Tests for Deadline client helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from libraries.automation.render.deadline_api import DeadlineClient
from libraries.automation.render.deadline_command import DeadlineCommandClient
from libraries.automation.render.deadline_jobs import build_command_job_payload


def test_build_command_job_payload_sets_metadata() -> None:
    payload = build_command_job_payload(
        name="Daily tests",
        executable="/usr/bin/python",
        job_kind="test",
        arguments=["-m", "pytest", "-q"],
        user="luffy",
        priority=55,
        pool="tests",
        environment={"CI": "1"},
        extra_job_info={"Comment": "nightly"},
    )

    job_info = payload["JobInfo"]
    plugin_info = payload["PluginInfo"]

    assert job_info["BatchName"] == "test"
    assert job_info["ExtraInfoKeyValue0"] == "job_kind=test"
    assert job_info["EnvironmentKeyValue0"] == "CI=1"
    assert job_info["UserName"] == "luffy"
    assert job_info["Pool"] == "tests"
    assert job_info["Priority"] == 55
    assert job_info["Comment"] == "nightly"
    assert plugin_info["Executable"] == "/usr/bin/python"
    assert plugin_info["Arguments"] == "-m pytest -q"


def test_deadline_client_submit_test_job_builds_payload() -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        content = b"{}"
        text = ""

        def json(self) -> Any:
            return {"jobId": "job-123"}

    class FakeSession:
        def post(self, url: str, json: Any, timeout: float, auth: Any) -> FakeResponse:
            captured["payload"] = json
            captured["url"] = url
            return FakeResponse()

    client = DeadlineClient(
        base_url="http://deadline",
        session_factory=FakeSession,
    )

    client.submit_test_job(
        name="pipeline smoke",
        executable="/usr/bin/python",
        arguments="-m pytest",
    )

    payload = captured["payload"]
    job_info = payload["JobInfo"]
    plugin_info = payload["PluginInfo"]

    assert job_info["BatchName"] == "test"
    assert job_info["ExtraInfoKeyValue0"] == "job_kind=test"
    assert job_info["Plugin"] == "CommandLine"
    assert plugin_info["Executable"] == "/usr/bin/python"
    assert plugin_info["Arguments"] == "-m pytest"


def test_command_client_submit_preset_job_writes_payload() -> None:
    captured: dict[str, str] = {}

    class RecordingCommandClient(DeadlineCommandClient):  # type: ignore[misc]
        def _run_command(self, args: list[str]) -> str:
            job_path = args[1]
            plugin_path = args[2]
            captured["job_info"] = Path(job_path).read_text(encoding="utf-8")
            captured["plugin_info"] = Path(plugin_path).read_text(encoding="utf-8")
            return "JobID=job-456"

    client = RecordingCommandClient(command="deadlinecommand")
    client.submit_preset_job(
        name="preset job",
        executable="/usr/bin/bash",
        arguments=["-lc", "echo preset"],
    )

    assert "BatchName=preset" in captured["job_info"]
    assert "ExtraInfoKeyValue0=job_kind=preset" in captured["job_info"]
    assert "Plugin=CommandLine" in captured["job_info"]
    assert "Executable=/usr/bin/bash" in captured["plugin_info"]
