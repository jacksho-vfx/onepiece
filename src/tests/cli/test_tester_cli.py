"""Tests for the tester demo CLI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.tester import app as tester_app
import apps.tester.presentation as tester_presentation


runner = CliRunner()


class DummyProcess:
    """Minimal stand-in for :class:`multiprocessing.Process`."""

    def __init__(self, *, target, args, daemon):  # type: ignore[no-untyped-def]
        self.target_callable = target
        self.args = args
        self.daemon = daemon
        self.started = False
        self.terminated = False
        self.joined = False
        self.join_timeout: float | None = None

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return False

    def terminate(self) -> None:
        self.terminated = True

    def join(self, timeout: float | None = None) -> None:
        self.joined = True
        self.join_timeout = timeout


@pytest.fixture
def demo_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[tuple[tester_app.DemoTarget, ...], dict[str, int]]:
    """Provide instrumented demo targets for CLI tests."""

    prepare_calls: dict[str, int] = {}

    def _make_target(
        label: str,
        import_path: str,
        port: int,
        *,
        environment: dict[str, str] | None = None,
        path: str = "/",
    ) -> tester_app.DemoTarget:
        prepare_calls[label] = 0

        def _prepare() -> None:
            prepare_calls[label] += 1

        return tester_app.DemoTarget(
            label=label,
            import_path=import_path,
            port=port,
            path=path,
            environment=environment,
            prepare=_prepare,
        )

    targets = (
        _make_target(
            "Alpha demo dashboard",
            "alpha.demo:app",
            9010,
            environment={"ALPHA_DASHBOARD_TOKEN": "alpha-token"},
        ),
        _make_target(
            "Beta control surface",
            "beta.control:app",
            9020,
            path="status",
        ),
    )

    monkeypatch.setattr(tester_app, "DEMO_TARGETS", targets)
    return targets, prepare_calls


@pytest.mark.parametrize(
    ("command", "additional_args"),
    [
        ("open", []),
        ("present", ["--skip-create"]),
    ],
)
def test_launch_commands_start_processes_and_open_browser(
    monkeypatch: pytest.MonkeyPatch,
    demo_targets: tuple[tuple[tester_app.DemoTarget, ...], dict[str, int]],
    command: str,
    additional_args: list[str],
) -> None:
    """Both launch commands should spawn processes and open browser tabs."""

    targets, _ = demo_targets
    processes: list[DummyProcess] = []
    opened_urls: list[str] = []
    requested_browser_names: list[str | None] = []
    observed_tokens: list[str | None] = []

    def fake_process(*args, **kwargs):  # type: ignore[no-untyped-def]
        observed_tokens.append(os.environ.get("ALPHA_DASHBOARD_TOKEN"))
        process = DummyProcess(*args, **kwargs)  # type: ignore[no-untyped-call]
        processes.append(process)
        return process

    class _DummyBrowser:
        def open(self, url, new):  # type: ignore[no-untyped-def]
            opened_urls.append(url)

    def fake_browser_get(name=None):  # type: ignore[no-untyped-def]
        requested_browser_names.append(name)
        return _DummyBrowser()

    monkeypatch.setattr(tester_app, "Process", fake_process)
    monkeypatch.setattr(tester_app, "_ensure_uvicorn", lambda: None)
    monkeypatch.setattr(tester_app.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tester_app.webbrowser, "get", fake_browser_get)
    monkeypatch.delenv("ALPHA_DASHBOARD_TOKEN", raising=False)

    result = runner.invoke(
        tester_app.app,
        [
            command,
            "--host",
            "127.0.0.42",
            "--log-level",
            "debug",
            "--browser-delay",
            "0",
            "--browser-path",
            "custom-browser",
            *additional_args,
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(processes) == len(targets)
    assert all(process.started for process in processes)

    expected_args = [
        (target.import_path, "127.0.0.42", target.port, "debug") for target in targets
    ]
    received_args = [process.args for process in processes]
    assert received_args == expected_args

    expected_urls = [target.url("127.0.0.42") for target in targets]
    assert opened_urls == expected_urls
    assert requested_browser_names == ["custom-browser"]

    assert "alpha-token" in observed_tokens
    assert os.environ.get("ALPHA_DASHBOARD_TOKEN") is None
    assert all(process.joined for process in processes)
    assert all(process.join_timeout == 5 for process in processes)


def test_present_runs_prepare_hooks_once(
    monkeypatch: pytest.MonkeyPatch,
    demo_targets: tuple[tuple[tester_app.DemoTarget, ...], dict[str, int]],
) -> None:
    """Each demo target's prepare hook should be invoked exactly once."""

    targets, prepare_calls = demo_targets
    processes: list[DummyProcess] = []

    def fake_process(*args, **kwargs):  # type: ignore[no-untyped-def]
        process = DummyProcess(*args, **kwargs)  # type: ignore[no-untyped-call]
        processes.append(process)
        return process

    monkeypatch.setattr(tester_app, "Process", fake_process)
    monkeypatch.setattr(tester_app, "_ensure_uvicorn", lambda: None)
    monkeypatch.setattr(tester_app.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tester_app.webbrowser, "get", lambda *_: None)

    result = runner.invoke(
        tester_app.app,
        ["present", "--browser-delay", "0", "--no-browser"],
    )

    assert result.exit_code == 0, result.output
    assert len(processes) == len(targets)
    for label, calls in prepare_calls.items():
        assert calls == 1, f"expected prepare hook for {label!r} to run once"


def test_present_restores_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment overrides should apply during launch and be restored afterwards."""

    processes: list[DummyProcess] = []
    observed_environment: list[tuple[str | None, str | None]] = []

    def fake_process(*args, **kwargs):  # type: ignore[no-untyped-def]
        observed_environment.append(
            (
                os.environ.get("TRAFALGAR_PIPELINE_API_URL"),
                os.environ.get("TRAFALGAR_DASHBOARD_TOKEN"),
            )
        )
        process = DummyProcess(*args, **kwargs)  # type: ignore[no-untyped-call]
        processes.append(process)
        return process

    demo_target = tester_app.DemoTarget(
        label="Pipeline API",
        import_path="demo.pipeline:app",
        port=9100,
        environment={
            "TRAFALGAR_PIPELINE_API_URL": "http://{host}:9999/",
            "TRAFALGAR_DASHBOARD_TOKEN": "demo-dashboard-token",
        },
    )

    monkeypatch.setattr(tester_app, "DEMO_TARGETS", (demo_target,))
    monkeypatch.setattr(tester_app, "Process", fake_process)
    monkeypatch.setattr(tester_app, "_ensure_uvicorn", lambda: None)
    monkeypatch.setattr(tester_app.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tester_app.webbrowser, "get", lambda *_: None)

    monkeypatch.setenv("TRAFALGAR_PIPELINE_API_URL", "https://existing.example/api/")
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", "existing-dashboard-token")

    result = runner.invoke(
        tester_app.app,
        ["present", "--browser-delay", "0", "--no-browser", "--skip-create"],
    )

    assert result.exit_code == 0, result.output
    assert len(processes) == 1
    assert observed_environment == [
        ("http://127.0.0.1:9999/", "demo-dashboard-token")
    ]
    assert os.environ["TRAFALGAR_PIPELINE_API_URL"] == "https://existing.example/api/"
    assert os.environ["TRAFALGAR_DASHBOARD_TOKEN"] == "existing-dashboard-token"
    assert processes[0].joined and processes[0].join_timeout == 5


@pytest.mark.parametrize(
    ("options", "expected_calls", "expected_message"),
    [
        ([], ["first", "second"], "Running demo creation hook"),
        (["--skip-create"], [], "Skipping demo creation hooks"),
    ],
)
def test_present_respects_skip_create_option(
    monkeypatch: pytest.MonkeyPatch,
    options: list[str],
    expected_calls: list[str],
    expected_message: str,
) -> None:
    """Creation hooks should honour the skip flag."""

    calls: list[str] = []

    def _make_hook(name: str) -> Any:
        def _hook() -> None:
            calls.append(name)

        _hook.__name__ = name  # help Typer echo a readable name
        return _hook

    hooks = (_make_hook("first"), _make_hook("second"))
    monkeypatch.setattr(tester_app, "DEMO_CREATION_HOOKS", hooks)

    launch_calls: list[dict[str, object]] = []

    def fake_launch(**kwargs):  # type: ignore[no-untyped-def]
        launch_calls.append(kwargs)

    monkeypatch.setattr(tester_app, "_launch_demo_targets", fake_launch)

    result = runner.invoke(
        tester_app.app,
        ["present", "--browser-delay", "0", "--no-browser", *options],
    )

    assert result.exit_code == 0, result.output
    assert expected_message in result.output
    assert calls == expected_calls
    assert len(launch_calls) == 1


def test_present_prepares_pipeline_demos(monkeypatch: pytest.MonkeyPatch) -> None:
    """The presentation command should stage and register pipeline demos."""

    class DummyOrchestrator:
        def __init__(self) -> None:
            self.registered: list[Any] = []

        def upsert(self, definition: Any) -> bool:
            self.registered.append(definition)
            return True

    dummy_orchestrator = DummyOrchestrator()
    monkeypatch.setattr(
        tester_presentation,
        "get_pipeline_orchestrator",
        lambda: dummy_orchestrator,
    )

    original_prepare = tester_presentation.prepare_pipeline_demos
    calls = 0

    def tracking_prepare() -> None:
        nonlocal calls
        original_prepare()
        calls += 1

    monkeypatch.setattr(tester_presentation, "prepare_pipeline_demos", tracking_prepare)
    monkeypatch.setattr(tester_app, "DEMO_CREATION_HOOKS", (tracking_prepare,))

    launch_calls: list[dict[str, object]] = []

    def fake_launch(**kwargs):  # type: ignore[no-untyped-def]
        launch_calls.append(kwargs)

    monkeypatch.setattr(tester_app, "_launch_demo_targets", fake_launch)
    monkeypatch.delenv("ONEPIECE_PROJECT_ROOT", raising=False)

    result = runner.invoke(
        tester_app.app,
        ["present", "--browser-delay", "0", "--no-browser"],
    )

    assert result.exit_code == 0, result.output
    assert calls == 1
    assert len(launch_calls) == 1

    staged_root = tester_presentation.get_staged_pipeline_project_root()
    assert staged_root is not None
    assert os.environ.get("ONEPIECE_PROJECT_ROOT") == str(staged_root)
    assert dummy_orchestrator.registered, "expected pipelines to be registered"

    tester_presentation.restore_pipeline_demo_environment()


def test_restore_pipeline_demo_environment_clears_staged_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Restoring the environment should clear the staged project root."""

    staged_root = tmp_path / "staged"
    project_root = staged_root / "demo"
    project_root.mkdir(parents=True)
    (project_root / "pipeline.yaml").write_text("name: demo\n", encoding="utf-8")

    monkeypatch.setattr(tester_presentation, "_stage_examples", lambda: staged_root)
    monkeypatch.setattr(
        tester_presentation, "translate_pipeline_manifest", lambda manifest: manifest
    )
    monkeypatch.setattr(
        tester_presentation,
        "pipeline_definition_from_profile_entry",
        lambda name, data: object(),
    )
    monkeypatch.setattr(
        tester_presentation,
        "_definition_with_stubbed_providers",
        lambda definition: definition,
    )

    class DummyOrchestrator:
        def __init__(self) -> None:
            self.registered: list[object] = []

        def upsert(self, definition: object) -> bool:
            self.registered.append(definition)
            return True

    orchestrator = DummyOrchestrator()
    monkeypatch.setattr(
        tester_presentation, "get_pipeline_orchestrator", lambda: orchestrator
    )
    monkeypatch.delenv("ONEPIECE_PROJECT_ROOT", raising=False)

    tester_presentation.prepare_pipeline_demos()

    assert tester_presentation.get_staged_pipeline_project_root() == project_root
    assert os.environ.get("ONEPIECE_PROJECT_ROOT") == str(project_root)

    tester_presentation.restore_pipeline_demo_environment()

    assert tester_presentation.get_staged_pipeline_project_root() is None
    assert os.environ.get("ONEPIECE_PROJECT_ROOT") is None
