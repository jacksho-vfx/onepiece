"""Tests for the render submission CLI."""

from __future__ import annotations

import getpass
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Generator

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app
from libraries.automation.render.base import RenderSubmissionError
from apps.onepiece.render import submit as submit_module
from apps.onepiece.utils.errors import (
    ExitCode,
    OnePieceExternalServiceError,
    OnePieceValidationError,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_capability_cache() -> Generator[None, None, None]:
    submit_module._refresh_capabilities_cache()
    yield
    submit_module._refresh_capabilities_cache()


def _capture_logger(
    log_events: list[tuple[str, str, dict[str, Any]]]
) -> SimpleNamespace:
    def _info(event: str, **kwargs: Any) -> None:
        log_events.append(("info", event, kwargs))

    def _error(event: str, **kwargs: Any) -> None:
        log_events.append(("error", event, kwargs))

    def _exception(event: str, **kwargs: Any) -> None:
        log_events.append(("exception", event, kwargs))

    return SimpleNamespace(info=_info, error=_error, exception=_exception)


def test_render_submit_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    called: dict[str, Any] = {}

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        called.update(
            {
                "scene": scene,
                "frames": frames,
                "output": output,
                "dcc": dcc,
                "priority": priority,
                "user": user,
                "chunk_size": chunk_size,
            }
        )
        return {
            "job_id": "job-123",
            "status": "queued",
            "farm_type": "mock",
        }

    log_events: list[tuple[str, str, dict[str, Any]]] = []

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 55,
            "priority_min": 10,
            "priority_max": 90,
            "chunk_size_enabled": True,
            "default_chunk_size": 4,
            "chunk_size_min": 1,
            "chunk_size_max": 10,
        },
    )
    monkeypatch.setattr(submit_module, "log", _capture_logger(log_events))

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "Nuke",
            "--scene",
            str(scene_file),
            "--frames",
            "1-10",
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Submitted nuke scene" in result.stdout
    assert called["scene"] == str(scene_file)
    assert called["output"] == str(output_dir)
    assert called["frames"] == "1-10"
    assert called["dcc"] == "nuke"
    assert called["priority"] == 65
    assert called["user"] == getpass.getuser()
    assert called["chunk_size"] == 2
    assert "Optimised submission" in result.stdout

    events = {(level, event) for level, event, _ in log_events}
    assert ("info", "render.submit.start") in events
    assert ("info", "render.submit.optimized") in events
    assert ("info", "render.submit.success") in events


def test_render_submit_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    scene_file = tmp_path / "shot01.ma"
    scene_file.write_text("requires maya")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    def failing_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        raise RenderSubmissionError("Adapter failure")

    log_events: list[tuple[str, str, dict[str, Any]]] = []

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", failing_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 50,
            "priority_min": 0,
            "priority_max": 100,
            "chunk_size_enabled": False,
        },
    )
    monkeypatch.setattr(submit_module, "log", _capture_logger(log_events))

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "maya",
            "--scene",
            str(scene_file),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, OnePieceExternalServiceError)
    assert result.exception.exit_code == ExitCode.EXTERNAL
    assert "Render submission failed: Adapter failure" in str(result.exception)

    events = {(level, event) for level, event, _ in log_events}
    assert ("info", "render.submit.start") in events
    assert ("error", "render.submit.failed") in events


def test_render_submit_reuses_capabilities_within_ttl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        return {
            "job_id": "job-456",
            "status": "queued",
            "farm_type": "mock",
        }

    capability_calls = 0

    def fake_capabilities() -> dict[str, Any]:
        nonlocal capability_calls
        capability_calls += 1
        return {
            "default_priority": 50,
            "priority_min": 10,
            "priority_max": 90,
            "chunk_size_enabled": True,
            "default_chunk_size": 5,
            "chunk_size_min": 1,
            "chunk_size_max": 10,
        }

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS, "mock", fake_capabilities
    )

    args = [
        "render",
        "submit",
        "--dcc",
        "Nuke",
        "--scene",
        str(scene_file),
        "--frames",
        "1-10",
        "--output",
        str(output_dir),
        "--farm",
        "mock",
    ]

    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.stdout

    assert capability_calls == 1


def test_render_submit_refresh_capabilities_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        return {
            "job_id": "job-789",
            "status": "queued",
            "farm_type": "mock",
        }

    capability_calls = 0

    def fake_capabilities() -> dict[str, Any]:
        nonlocal capability_calls
        capability_calls += 1
        return {
            "default_priority": 45,
            "priority_min": 5,
            "priority_max": 95,
            "chunk_size_enabled": False,
        }

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS, "mock", fake_capabilities
    )

    base_args = [
        "render",
        "submit",
        "--dcc",
        "Nuke",
        "--scene",
        str(scene_file),
        "--frames",
        "1-10",
        "--output",
        str(output_dir),
        "--farm",
        "mock",
    ]

    first = runner.invoke(app, base_args)
    assert first.exit_code == 0, first.stdout

    refreshed = runner.invoke(app, base_args + ["--refresh-capabilities"])
    assert refreshed.exit_code == 0, refreshed.stdout

    assert capability_calls == 2


def test_render_submit_ignores_default_chunk_when_adapter_disables_chunking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot01.blend"
    scene_file.write_text("requires blender")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    captured: dict[str, Any] = {}

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        captured.update(
            {
                "scene": scene,
                "frames": frames,
                "output": output,
                "dcc": dcc,
                "priority": priority,
                "user": user,
                "chunk_size": chunk_size,
            }
        )
        return {
            "job_id": "job-789",
            "status": "submitted",
            "farm_type": "mock",
        }

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 42,
            "priority_min": 0,
            "priority_max": 100,
            "chunk_size_enabled": False,
            "default_chunk_size": 6,
        },
    )

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "blender",
            "--scene",
            str(scene_file),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Submitted blender scene" in result.stdout
    assert captured["priority"] == 42
    assert captured["chunk_size"] is None


def test_render_submit_manual_overrides_bypass_optimization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot02.nk"
    scene_file.write_text("print('manual overrides')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    captured: dict[str, Any] = {}

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        captured.update(
            {
                "scene": scene,
                "frames": frames,
                "output": output,
                "dcc": dcc,
                "priority": priority,
                "user": user,
                "chunk_size": chunk_size,
            }
        )
        return {
            "job_id": "job-321",
            "status": "queued",
            "farm_type": "mock",
        }

    log_events: list[tuple[str, str, dict[str, Any]]] = []

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 55,
            "priority_min": 10,
            "priority_max": 90,
            "chunk_size_enabled": True,
            "default_chunk_size": 4,
            "chunk_size_min": 1,
            "chunk_size_max": 10,
        },
    )
    monkeypatch.setattr(submit_module, "log", _capture_logger(log_events))

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "Nuke",
            "--scene",
            str(scene_file),
            "--frames",
            "1-10",
            "--output",
            str(output_dir),
            "--priority",
            "72",
            "--chunk-size",
            "6",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["priority"] == 72
    assert captured["chunk_size"] == 6

    optimisation_events = [event for event in log_events if event[1] == "render.submit.optimized"]
    assert optimisation_events, "Expected optimisation summary log"
    for _, _, payload in optimisation_events:
        assert payload.get("applied") is False


def test_render_submit_no_optimize_uses_adapter_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot03.nk"
    scene_file.write_text("print('no optimize')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    captured: dict[str, Any] = {}

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        captured.update(
            {
                "scene": scene,
                "frames": frames,
                "output": output,
                "dcc": dcc,
                "priority": priority,
                "user": user,
                "chunk_size": chunk_size,
            }
        )
        return {
            "job_id": "job-654",
            "status": "queued",
            "farm_type": "mock",
        }

    log_events: list[tuple[str, str, dict[str, Any]]] = []

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 55,
            "priority_min": 10,
            "priority_max": 90,
            "chunk_size_enabled": True,
            "default_chunk_size": 4,
            "chunk_size_min": 1,
            "chunk_size_max": 10,
        },
    )
    monkeypatch.setattr(submit_module, "log", _capture_logger(log_events))

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "Nuke",
            "--scene",
            str(scene_file),
            "--frames",
            "1-10",
            "--output",
            str(output_dir),
            "--no-optimize",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["priority"] == 55
    assert captured["chunk_size"] == 4

    events = {(level, event) for level, event, _ in log_events}
    assert ("info", "render.submit.optimized") not in events


def test_render_submit_priority_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot01.hip"
    scene_file.write_text("requires houdini")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        return {}

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 50,
            "priority_min": 1,
            "priority_max": 100,
            "chunk_size_enabled": True,
            "chunk_size_min": 1,
            "chunk_size_max": 10,
        },
    )

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "houdini",
            "--scene",
            str(scene_file),
            "--output",
            str(output_dir),
            "--priority",
            "200",
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, OnePieceValidationError)
    assert result.exception.exit_code == ExitCode.VALIDATION
    assert "supported maximum" in str(result.exception)


def test_render_preset_crud_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    preset_dir = tmp_path / "presets"
    monkeypatch.setenv("ONEPIECE_RENDER_PRESET_DIR", str(preset_dir))

    captured: dict[str, Any] = {}

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        captured.update(
            {
                "scene": scene,
                "frames": frames,
                "output": output,
                "dcc": dcc,
                "priority": priority,
                "user": user,
                "chunk_size": chunk_size,
            }
        )
        return {
            "job_id": "job-456",
            "status": "submitted",
            "farm_type": "mock",
        }

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 65,
            "priority_min": 10,
            "priority_max": 90,
            "chunk_size_enabled": True,
            "default_chunk_size": 3,
            "chunk_size_min": 1,
            "chunk_size_max": 8,
        },
    )

    save_result = runner.invoke(
        app,
        [
            "render",
            "preset",
            "save",
            "daily_nuke",
            "--farm",
            "mock",
            "--dcc",
            "nuke",
            "--frames",
            "1-20",
        ],
    )

    assert save_result.exit_code == 0, save_result.stdout
    assert "Saved preset" in save_result.stdout

    list_result = runner.invoke(app, ["render", "preset", "list"])
    assert list_result.exit_code == 0
    assert "daily_nuke" in list_result.stdout

    use_result = runner.invoke(
        app,
        [
            "render",
            "preset",
            "use",
            "daily_nuke",
            "--scene",
            str(scene_file),
            "--output",
            str(output_dir),
        ],
    )

    assert use_result.exit_code == 0, use_result.stdout
    assert "Submitted nuke scene" in use_result.stdout
    assert captured["scene"] == str(scene_file)
    assert captured["output"] == str(output_dir)
    assert captured["frames"] == "1-20"
    assert captured["dcc"] == "nuke"
    assert captured["priority"] == 65
    assert captured["chunk_size"] == 3


def test_render_preset_save_handles_capability_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preset_dir = tmp_path / "presets"
    monkeypatch.setenv("ONEPIECE_RENDER_PRESET_DIR", str(preset_dir))

    def failing_capabilities() -> dict[str, Any]:
        raise RenderSubmissionError("capabilities offline")

    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS, "mock", failing_capabilities
    )

    result = runner.invoke(
        app,
        [
            "render",
            "preset",
            "save",
            "offline_mock",
            "--farm",
            "mock",
            "--dcc",
            "nuke",
        ],
    )

    assert result.exit_code == 0, result.stdout

    preset_file = preset_dir / "offline_mock.json"
    payload = json.loads(preset_file.read_text())

    assert payload["farm"] == "mock"
    assert payload.get("dcc") == "nuke"
    assert "priority" not in payload
    assert "chunk_size" not in payload


def test_render_submit_requires_existing_scene(tmp_path: Path) -> None:
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    missing_scene = tmp_path / "missing.nk"

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "nuke",
            "--scene",
            str(missing_scene),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, OnePieceValidationError)
    assert "does not exist" in str(result.exception)


def test_render_submit_requires_output_directory(tmp_path: Path) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")

    output_file = tmp_path / "renders.txt"
    output_file.write_text("not a directory")

    result_missing = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "nuke",
            "--scene",
            str(scene_file),
            "--output",
            str(tmp_path / "missing"),
        ],
    )

    assert result_missing.exit_code != 0
    assert isinstance(result_missing.exception, OnePieceValidationError)
    assert "does not exist" in str(result_missing.exception)

    result_not_dir = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "nuke",
            "--scene",
            str(scene_file),
            "--output",
            str(output_file),
        ],
    )

    assert result_not_dir.exit_code != 0
    assert isinstance(result_not_dir.exception, OnePieceValidationError)
    assert "not a directory" in str(result_not_dir.exception)
