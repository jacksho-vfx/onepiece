import io
from pathlib import Path
from typing import Generator, Sequence

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from libraries.integrations.aws import s5_sync


class DummyProcess:
    """Minimal :class:`subprocess.Popen` substitute for streaming tests."""

    def __init__(
        self,
        *,
        stdout_lines: Sequence[str],
        stderr_lines: Sequence[str] | None = None,
        returncode: int = 0,
    ) -> None:
        self.returncode = returncode
        self.stdout = io.StringIO(_join_lines(stdout_lines))
        stderr = stderr_lines or []
        self.stderr = io.StringIO(_join_lines(stderr)) if stderr else io.StringIO("")

    def wait(self) -> int:
        return self.returncode


def _join_lines(lines: Sequence[str]) -> str:
    text = "\n".join(lines)
    if text:
        text += "\n"
    return text


def test_s5_sync_counts_download_events(
    monkeypatch: MonkeyPatch, capsys: Generator[CaptureFixture[str], None, None]
) -> None:
    """Downloads must contribute to the progress summary totals."""

    process = DummyProcess(stdout_lines=["download fileA", "download fileB"])
    monkeypatch.setattr(s5_sync.subprocess, "Popen", lambda *args, **kwargs: process)

    s5_sync.s5_sync("s3://bucket/context", Path("/tmp/output"))

    captured = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Total files: 2" in captured
    assert "Downloaded: 2" in captured
    assert "Uploaded:   0" in captured


def test_s5_sync_accepts_concurrency_and_part_size(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    process = DummyProcess(stdout_lines=[])

    def _fake_popen(cmd: list[str], **kwargs: object) -> DummyProcess:
        captured["cmd"] = cmd
        return process

    monkeypatch.setattr(s5_sync.subprocess, "Popen", _fake_popen)

    s5_sync.s5_sync(
        Path("/tmp/source"),
        "s3://bucket/context",
        concurrency=8,
        part_size="64MB",
    )

    command = captured["cmd"]
    assert "--concurrency" in command
    assert "8" in command
    assert "--part-size" in command
    assert "64MB" in command
