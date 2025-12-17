from __future__ import annotations

from pathlib import Path

import pytest

from libraries.creative.dcc.nuke import script_launcher
from libraries.creative.dcc.nuke.script_launcher import (
    ScriptDefinition,
    discover_script_definitions,
)


def test_script_definition_from_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executed: list[str] = []

    def _fake_run_path(path: str, *, run_name: str) -> None:
        executed.append(path)

    monkeypatch.setattr(script_launcher.runpy, "run_path", _fake_run_path)

    script_file = tmp_path / "cleanup_tools.py"
    script_file.write_text("print('Hello from script')", encoding="utf-8")

    definition = ScriptDefinition.from_path(script_file)
    definition.run()

    assert executed == [str(script_file.resolve())]


def test_discover_script_definitions_ignores_init(tmp_path: Path) -> None:
    (tmp_path / "material_harmonizer.py").write_text("# package", encoding="utf-8")
    alpha = tmp_path / "alpha.py"
    beta = tmp_path / "beta.py"
    alpha.touch()
    beta.touch()

    discovered = discover_script_definitions(tmp_path)

    assert [definition.label for definition in discovered] == [
        "Alpha",
        "Beta",
    ]


def test_script_launcher_requires_qt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script_launcher, "QtWidgets", None)
    monkeypatch.setattr(script_launcher, "QtCore", None)

    with pytest.raises(RuntimeError):
        script_launcher.ScriptLauncherWidget()
