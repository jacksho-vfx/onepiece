"""Tests for the tester demo CLI."""

from __future__ import annotations

import os
from types import SimpleNamespace

from _pytest.monkeypatch import MonkeyPatch
from typer.testing import CliRunner

from apps.tester import app as tester_app


class DummyProcess:
    """Minimal stand-in for :class:`multiprocessing.Process`."""

    def __init__(self, target, args, daemon):  # type: ignore[no-untyped-def]
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        self.terminated = False
        self.joined = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return False

    def terminate(self) -> None:
        self.terminated = True

    def join(self, timeout: float | None = None) -> None:
        self.joined = True
        self.join_timeout = timeout


def test_open_launches_demo_targets(monkeypatch: MonkeyPatch) -> None:
    """The CLI should spawn uvicorn processes and open browser tabs."""

    runner = CliRunner()
    processes: list[DummyProcess] = []
    opened_urls: list[str] = []

    def fake_process(*args, **kwargs):  # type: ignore[no-untyped-def]
        process = DummyProcess(*args, **kwargs)  # type: ignore[no-untyped-call]
        processes.append(process)
        return process

    monkeypatch.setattr(tester_app, "Process", fake_process)
    monkeypatch.setattr(tester_app, "_ensure_uvicorn", lambda: None)
    monkeypatch.setattr(tester_app.time, "sleep", lambda *_: None)

    def fake_browser_get(name=None):  # type: ignore[no-untyped-def]
        assert name is None
        return SimpleNamespace(open=lambda url, new: opened_urls.append(url))

    monkeypatch.setattr(tester_app.webbrowser, "get", fake_browser_get)

    result = runner.invoke(
        tester_app.app,
        ["--host", "127.0.0.1", "--browser-delay", "0"],
    )

    assert result.exit_code == 0, result.output
    assert len(processes) == len(tester_app.DEMO_TARGETS)
    assert all(process.started for process in processes)

    expected_args = [
        (target.import_path, "127.0.0.1", target.port, tester_app.DEFAULT_LOG_LEVEL)
        for target in tester_app.DEMO_TARGETS
    ]
    received_args = [process.args for process in processes]
    assert received_args == expected_args

    expected_urls = [target.url("127.0.0.1") for target in tester_app.DEMO_TARGETS]
    assert opened_urls == expected_urls

    assert all(process.joined for process in processes)


def test_open_exports_demo_environment(monkeypatch: MonkeyPatch) -> None:
    """Environment variables declared by demo targets should be exported."""

    runner = CliRunner()
    processes: list[DummyProcess] = []
    observed_tokens: list[str | None] = []

    def fake_process(*args, **kwargs):  # type: ignore[no-untyped-def]
        observed_tokens.append(os.environ.get("TRAFALGAR_DASHBOARD_TOKEN"))
        process = DummyProcess(*args, **kwargs)  # type: ignore[no-untyped-call]
        processes.append(process)
        return process

    monkeypatch.setattr(tester_app, "Process", fake_process)
    monkeypatch.setattr(tester_app, "_ensure_uvicorn", lambda: None)
    monkeypatch.setattr(tester_app.time, "sleep", lambda *_: None)

    # Ensure the environment starts without the Trafalgar token.
    monkeypatch.delenv("TRAFALGAR_DASHBOARD_TOKEN", raising=False)

    result = runner.invoke(
        tester_app.app,
        ["--browser-delay", "0", "--no-browser"],
    )

    assert result.exit_code == 0, result.output

    token_value = None
    for target in tester_app.DEMO_TARGETS:
        env = target.environment or {}
        if "TRAFALGAR_DASHBOARD_TOKEN" in env:
            token_value = env["TRAFALGAR_DASHBOARD_TOKEN"]
            break

    assert token_value is not None
    assert token_value in observed_tokens
    assert os.environ.get("TRAFALGAR_DASHBOARD_TOKEN") is None
    assert all(process.joined for process in processes)
