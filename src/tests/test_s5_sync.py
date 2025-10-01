"""Tests for the lightweight s5cmd wrapper."""

from __future__ import annotations

from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest
from upath import UPath

from libraries.aws.s5_sync import s5_sync


class DummyProcess:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = StringIO(stdout)
        self.stderr = StringIO(stderr)

    def wait(self) -> int:
        return self.returncode


@patch("libraries.aws.s5_sync.subprocess.Popen")
def test_s5_sync_raises_for_non_zero_return_code(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(
        returncode=2,
        stdout="upload file.txt\n",
        stderr="failed to connect",
    )

    with pytest.raises(RuntimeError) as excinfo:
        s5_sync(UPath("/local/path"), "s3://bucket/context")

    error_message = str(excinfo.value)
    assert "exit code 2" in error_message
    assert "failed to connect" in error_message


@patch("libraries.aws.s5_sync.subprocess.Popen")
def test_s5_sync_raises_for_non_zero_without_stderr(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(
        returncode=1,
        stdout="",
        stderr="",
    )

    with pytest.raises(RuntimeError) as excinfo:
        s5_sync(UPath("/local/path"), "s3://bucket/context")

    assert "No additional error output from s5cmd" in str(excinfo.value)


@patch("libraries.aws.s5_sync.subprocess.Popen")
def test_s5_sync_upload_command_order(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(returncode=0, stdout="upload file\n")

    s5_sync(
        source=UPath("/local/path"),
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


@patch("libraries.aws.s5_sync.subprocess.Popen")
def test_s5_sync_download_command_order(mock_popen: Any) -> None:
    mock_popen.return_value = DummyProcess(
        returncode=0, stdout="download file\n"
    )

    s5_sync(
        source="s3://bucket/context",
        destination=UPath("/local/path"),
    )

    expected_cmd = [
        "s5cmd",
        "sync",
        "s3://bucket/context/",
        "/local/path/",
    ]

    assert mock_popen.call_args.args[0] == expected_cmd
