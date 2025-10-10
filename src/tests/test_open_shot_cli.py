from __future__ import annotations

from enum import Enum
from pathlib import Path

from importlib import import_module

from typer.testing import CliRunner

open_shot_module = import_module("apps.onepiece.dcc.open_shot")


class DummyDCC(Enum):
    MAYA = "maya"


def test_open_shot_invokes_dcc_open_scene(monkeypatch, tmp_path: Path) -> None:
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

    monkeypatch.setattr(open_shot_module, "validate_dcc", fake_validate_dcc)
    monkeypatch.setattr(open_shot_module, "open_scene", fake_open_scene)

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

