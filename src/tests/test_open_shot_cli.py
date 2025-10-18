from __future__ import annotations

from enum import Enum
from pathlib import Path
from types import SimpleNamespace

from importlib import import_module

from _pytest.monkeypatch import MonkeyPatch
from typer.testing import CliRunner

open_shot_module = import_module("apps.onepiece.dcc.open_shot")


class DummyDCC(Enum):
    MAYA = "maya"


def test_open_shot_invokes_dcc_open_scene(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """The CLI should resolve the DCC and invoke :func:`open_scene`."""

    shot_path = tmp_path / "example.ma"
    shot_path.write_text("// dummy maya scene")

    runner = CliRunner()
    received: dict[str, object] = {}

    def fake_validate_dcc(value: str) -> DummyDCC:
        assert value == "maya"
        return DummyDCC.MAYA

    def fake_open_scene(dcc: DummyDCC, path: Path) -> None:
        received["dcc"] = dcc
        received["path"] = path

    def fake_check_environment(dcc: DummyDCC) -> SimpleNamespace:
        assert dcc is DummyDCC.MAYA
        return SimpleNamespace(
            dcc=dcc,
            installed=True,
            executable="/usr/bin/maya",
            plugins=SimpleNamespace(missing=frozenset()),
            gpu=SimpleNamespace(meets_requirement=True),
        )

    monkeypatch.setattr(open_shot_module, "validate_dcc", fake_validate_dcc)
    monkeypatch.setattr(open_shot_module, "open_scene", fake_open_scene)
    monkeypatch.setattr(open_shot_module, "check_dcc_environment", fake_check_environment)

    result = runner.invoke(
        open_shot_module.app,
        [
            "--shot",
            str(shot_path),
            "--dcc",
            "maya",
        ],
    )

    assert result.exit_code == 0, result.output
    assert received["dcc"] is DummyDCC.MAYA
    assert received["path"] == shot_path
    assert isinstance(received["path"], Path)


def test_open_shot_reports_validation_failures(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """The CLI surfaces validation failures with actionable messaging."""

    shot_path = tmp_path / "example.ma"
    shot_path.write_text("// dummy maya scene")

    runner = CliRunner()

    def fake_validate_dcc(value: str) -> DummyDCC:
        assert value == "maya"
        return DummyDCC.MAYA

    def fake_open_scene(*_: object) -> None:
        raise AssertionError("open_scene should not be called when validation fails")

    def fake_check_environment(dcc: DummyDCC) -> SimpleNamespace:
        assert dcc is DummyDCC.MAYA
        return SimpleNamespace(
            dcc=dcc,
            installed=True,
            executable="/usr/bin/maya",
            plugins=SimpleNamespace(missing=frozenset({"arnold"})),
            gpu=SimpleNamespace(
                meets_requirement=False,
                required="RTX 3090",
                detected="GTX 1080",
            ),
        )

    monkeypatch.setattr(open_shot_module, "validate_dcc", fake_validate_dcc)
    monkeypatch.setattr(open_shot_module, "open_scene", fake_open_scene)
    monkeypatch.setattr(open_shot_module, "check_dcc_environment", fake_check_environment)

    result = runner.invoke(
        open_shot_module.app,
        [
            "--shot",
            str(shot_path),
            "--dcc",
            "maya",
        ],
    )

    assert result.exit_code == open_shot_module.OnePieceExternalServiceError.exit_code
    assert "Missing required plugins: arnold" in result.output
    assert "GPU requirement not satisfied (required: RTX 3090; detected: GTX 1080)." in result.output


def test_open_shot_skip_validation_flag(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """`--skip-validation` bypasses environment checks."""

    shot_path = tmp_path / "example.ma"
    shot_path.write_text("// dummy maya scene")

    runner = CliRunner()
    received: dict[str, object] = {}

    def fake_validate_dcc(value: str) -> DummyDCC:
        assert value == "maya"
        return DummyDCC.MAYA

    def fake_open_scene(dcc: DummyDCC, path: Path) -> None:
        received["dcc"] = dcc
        received["path"] = path

    def fake_check_environment(*_: object) -> None:
        raise AssertionError("check_dcc_environment should be skipped")

    monkeypatch.setattr(open_shot_module, "validate_dcc", fake_validate_dcc)
    monkeypatch.setattr(open_shot_module, "open_scene", fake_open_scene)
    monkeypatch.setattr(open_shot_module, "check_dcc_environment", fake_check_environment)

    result = runner.invoke(
        open_shot_module.app,
        [
            "--shot",
            str(shot_path),
            "--dcc",
            "maya",
            "--skip-validation",
        ],
    )

    assert result.exit_code == 0, result.output
    assert received["dcc"] is DummyDCC.MAYA
    assert received["path"] == shot_path
