"""Regression tests covering CLI exit code mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apps.onepiece import __main__ as cli_main
from apps.onepiece.render import submit as submit_module
from apps.onepiece.utils.errors import ExitCode
from libraries.render.base import RenderSubmissionError


def _install_mock_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    capabilities: dict[str, Any] | None = None,
    adapter_result: dict[str, Any] | None = None,
    adapter_error: Exception | None = None,
) -> None:
    """Install a mock render adapter and capabilities provider for tests."""

    if capabilities is None:
        capabilities = {
            "default_priority": 50,
            "priority_min": 0,
            "priority_max": 100,
            "chunk_size_enabled": False,
        }

    def _capabilities() -> dict[str, Any]:
        return capabilities

    def _adapter(**_: Any) -> dict[str, Any]:
        if adapter_error is not None:
            raise adapter_error
        return adapter_result or {
            "job_id": "job-1",
            "status": "queued",
            "farm_type": "mock",
        }

    monkeypatch.setitem(submit_module.FARM_CAPABILITY_PROVIDERS, "mock", _capabilities)
    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", _adapter)


def _submission_args(scene: Path, output: Path, *extra: str) -> list[str]:
    return [
        "render",
        "submit",
        "--dcc",
        "nuke",
        "--scene",
        str(scene),
        "--output",
        str(output),
        *extra,
    ]


def test_main_returns_success_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_mock_adapter(monkeypatch)

    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    exit_code = cli_main.main(_submission_args(scene_file, output_dir))

    assert exit_code == ExitCode.SUCCESS


def test_main_maps_validation_errors_to_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_mock_adapter(
        monkeypatch,
        capabilities={
            "default_priority": 50,
            "priority_min": 10,
            "priority_max": 20,
            "chunk_size_enabled": False,
        },
    )

    scene_file = tmp_path / "shot02.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    exit_code = cli_main.main(
        _submission_args(scene_file, output_dir, "--priority", "5")
    )

    assert exit_code == ExitCode.VALIDATION


def test_main_maps_adapter_failures_to_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_mock_adapter(
        monkeypatch,
        adapter_error=RenderSubmissionError("Adapter failure"),
    )

    scene_file = tmp_path / "shot03.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    exit_code = cli_main.main(_submission_args(scene_file, output_dir))

    assert exit_code == ExitCode.EXTERNAL
