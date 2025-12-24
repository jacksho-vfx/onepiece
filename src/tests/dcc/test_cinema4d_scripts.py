from __future__ import annotations

from pathlib import Path

from libraries.creative.dcc.cinema4d.script_library import (
    Cinema4DScript,
    deploy_scripts_to_directory,
    discover_cinema4d_scripts,
)


def test_discover_cinema4d_scripts_reads_docstring(tmp_path: Path) -> None:
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    script_path = script_dir / "hello_world.py"
    script_path.write_text('"""Says hello from Cinema 4D."""\nprint("hello")\n')

    scripts = discover_cinema4d_scripts(script_dir)

    assert len(scripts) == 1
    assert scripts[0].label == "Hello World"
    assert scripts[0].description == "Says hello from Cinema 4D."


def test_deploy_scripts_to_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"

    script_path = source / "tool.py"
    script_path.write_text("print('tool')\n")
    scripts = [Cinema4DScript.from_path(script_path)]

    copied = deploy_scripts_to_directory(destination, scripts)

    assert len(copied) == 1
    assert copied[0].exists()
    assert copied[0].read_text() == script_path.read_text()
