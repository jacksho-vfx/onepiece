"""Tests for the lightweight s5cmd wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from libraries.integrations.aws.s5_sync import s5_sync


class DummyProcess:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self) -> tuple[str, str]:
        return self._stdout, self._stderr


@patch("libraries.integrations.aws.s5_sync.subprocess.Popen")
def test_s5_sync_raises_for_non_zero_return_code(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(
        returncode=2,
        stdout="upload file.txt\n",
        stderr="failed to connect",
    )

    with pytest.raises(RuntimeError) as excinfo:
        s5_sync(Path("/local/path"), "s3://bucket/context")

    error_message = str(excinfo.value)
    assert "exit code 2" in error_message
    assert "failed to connect" in error_message


@patch("libraries.integrations.aws.s5_sync.subprocess.Popen")
def test_s5_sync_raises_for_non_zero_without_stderr(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(
        returncode=1,
        stdout="",
        stderr="",
    )

    with pytest.raises(RuntimeError) as excinfo:
        s5_sync(Path("/local/path"), "s3://bucket/context")

    assert "No additional error output from s5cmd" in str(excinfo.value)


@patch("libraries.integrations.aws.s5_sync.subprocess.Popen")
def test_s5_sync_handles_stderr_output(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(
        returncode=0,
        stdout="upload file.txt\n",
        stderr="warning: throttling\n",
    )

    progress = Mock()

    s5_sync(Path("/local/path"), "s3://bucket/context", progress_callback=progress)

    progress.assert_called_once_with("upload file.txt")


@patch("libraries.integrations.aws.s5_sync.subprocess.Popen")
def test_s5_sync_upload_command_order(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(returncode=0, stdout="upload file\n")

    s5_sync(
        source=Path("/local/path"),
        destination="s3://bucket/context",
        include=["*.exr"],
        exclude=["*.tmp"],
    )

    expected_cmd = [
        "s5cmd",
        "sync",
        "--include",
        "*.exr",
        "--exclude",
        "*.tmp",
        "/local/path/",
        "s3://bucket/context/",
    ]

    assert mock_popen.call_args.args[0] == expected_cmd
    assert mock_popen.call_args.kwargs["env"] is None


@patch("libraries.integrations.aws.s5_sync.subprocess.Popen")
def test_s5_sync_download_command_order(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(returncode=0, stdout="download file\n")

    s5_sync(
        source="s3://bucket/context",
        destination=Path("/local/path"),
    )

    expected_cmd = [
        "s5cmd",
        "sync",
        "s3://bucket/context/",
        "/local/path/",
    ]

    assert mock_popen.call_args.args[0] == expected_cmd


@patch("libraries.integrations.aws.s5_sync.subprocess.Popen")
def test_s5_sync_sets_profile_env(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(returncode=0, stdout="upload file\n")

    s5_sync(
        source=Path("/local/path"),
        destination="s3://bucket/context",
        profile="artist",
    )

    env = mock_popen.call_args.kwargs["env"]
    assert env is not None
    assert env["AWS_PROFILE"] == "artist"
