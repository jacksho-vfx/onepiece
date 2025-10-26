"""Regression tests for the s5_sync helper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from libraries.integrations.aws.s5_sync import s5_sync


class _DummyProcess:
    """Minimal stand-in for subprocess.Popen return values."""

    def __init__(self) -> None:
        self.returncode = 0
        self.stdout = iter(())
        self.stderr = iter(())

    def wait(self) -> None:
        return None


def test_s5_sync_uses_profile_environment(monkeypatch: Any) -> None:
    """Providing a profile should propagate AWS_PROFILE to the child process."""

    captured: dict[str, Any] = {}

    def _fake_popen(*args: Any, **kwargs: Any) -> _DummyProcess:
        captured["env"] = kwargs.get("env")
        return _DummyProcess()

    monkeypatch.setattr(
        "libraries.integrations.aws.s5_sync.subprocess.Popen", _fake_popen
    )

    s5_sync(Path("/local/path"), "s3://bucket/context", profile="artist")

    env = captured.get("env")
    assert env is not None
    assert env["AWS_PROFILE"] == "artist"
