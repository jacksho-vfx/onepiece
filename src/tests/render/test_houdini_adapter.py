"""Unit tests for the Houdini render adapter."""

from __future__ import annotations

import subprocess
import uuid
from typing import Any

import pytest

from libraries.automation.render import config as render_config
from libraries.automation.render import houdini
from libraries.automation.render.base import (
    RenderAdapterConfigurationError,
    RenderAdapterJobRejectedError,
    RenderAdapterUnavailableError,
)


@pytest.fixture(autouse=True)
def reset_houdini_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Ensure tests start with clean caches and environment."""

    render_config.get_adapter_settings.cache_clear()
    monkeypatch.delenv("RENDER_HOUDINI_RENDERER", raising=False)
    monkeypatch.delenv("RENDER_HOUDINI_HRENDER_PATH", raising=False)
    monkeypatch.delenv("RENDER_HOUDINI_HUSK_PATH", raising=False)
    yield
    render_config.get_adapter_settings.cache_clear()


def test_submit_job_hrender_builds_command(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, Any] = {}

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        executed["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="queued", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=0))

    result = houdini.submit_job(
        scene="/path/to/scene.hip",
        frames="1-10x2",
        output="/tmp/output",
        dcc="houdini",
        priority=50,
        user="robin",
        chunk_size=None,
    )

    assert result == {
        "job_id": "houdini-00000000000000000000000000000000",
        "status": "submitted",
        "farm_type": "houdini",
        "message": "queued",
    }
    assert executed["command"] == [
        "hrender",
        "-e",
        "-f",
        "1",
        "10",
        "2",
        "-o",
        "/tmp/output",
        "/path/to/scene.hip",
    ]


def test_submit_job_uses_husk_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="submitted", stderr="")

    monkeypatch.setenv("RENDER_HOUDINI_RENDERER", "husk")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = houdini.submit_job(
        scene="/path/to/scene.usd",
        frames="5",
        output="/tmp/out.usd",
        dcc="houdini",
        priority=40,
        user="nami",
        chunk_size=None,
    )

    assert result["message"] == "submitted"


def test_submit_job_rejects_invalid_frames() -> None:
    with pytest.raises(RenderAdapterConfigurationError):
        houdini.submit_job(
            scene="/scene.hip",
            frames="1-10,20-30",
            output="/tmp/out",
            dcc="houdini",
            priority=10,
            user="zoro",
            chunk_size=None,
        )


def test_submit_job_rejects_chunk_size() -> None:
    with pytest.raises(RenderAdapterConfigurationError):
        houdini.submit_job(
            scene="/scene.hip",
            frames="1-5",
            output="/tmp/out",
            dcc="houdini",
            priority=10,
            user="nami",
            chunk_size=5,
        )


def test_submit_job_reports_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RenderAdapterUnavailableError):
        houdini.submit_job(
            scene="/scene.hip",
            frames="1-5",
            output="/tmp/out",
            dcc="houdini",
            priority=10,
            user="nami",
            chunk_size=None,
        )


def test_submit_job_reports_rejected_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, command, output="bad frames", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RenderAdapterJobRejectedError):
        houdini.submit_job(
            scene="/scene.hip",
            frames="1-5",
            output="/tmp/out",
            dcc="houdini",
            priority=10,
            user="nami",
            chunk_size=None,
        )


def test_get_capabilities_returns_defaults() -> None:
    caps = houdini.get_capabilities()

    assert caps["default_priority"] == 50
    assert caps["chunk_size_enabled"] is False
