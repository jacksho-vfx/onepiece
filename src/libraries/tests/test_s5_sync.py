from typing import Any
from unittest.mock import patch

import pytest
from upath import UPath

from libraries.aws.s5_sync import s5_sync


class DummyCompletedProcess:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@patch("libraries.aws.s5_sync.subprocess.run")
def test_s5_sync_raises_for_non_zero_return_code(mock_run: Any) -> None:
    mock_run.return_value = DummyCompletedProcess(
        returncode=2,
        stdout="upload file.txt\n",
        stderr="failed to connect",
    )

    with pytest.raises(RuntimeError) as excinfo:
        s5_sync(UPath("/local/path"), "bucket", "context")

    error_message = str(excinfo.value)
    assert "exit code 2" in error_message
    assert "failed to connect" in error_message


@patch("libraries.aws.s5_sync.subprocess.run")
def test_s5_sync_raises_for_non_zero_without_stderr(mock_run: Any) -> None:
    mock_run.return_value = DummyCompletedProcess(
        returncode=1,
        stdout="",
        stderr="",
    )

    with pytest.raises(RuntimeError) as excinfo:
        s5_sync(UPath("/local/path"), "bucket", "context")

    assert "No additional error output" in str(excinfo.value)
