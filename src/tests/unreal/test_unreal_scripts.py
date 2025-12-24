from __future__ import annotations

from pathlib import Path

from libraries.creative.dcc.unreal.deploy import (
    available_script_files,
    deploy_unreal_resources,
    get_script_library_path,
)
from libraries.creative.dcc.unreal.scripts import discover_unreal_scripts


def test_discover_unreal_scripts_reads_bundled_library() -> None:
    directory = get_script_library_path()
    definitions = discover_unreal_scripts(directory)

    labels = {definition.label for definition in definitions}
    assert {
        path.name
        for path in directory.iterdir()
        if path.suffix == ".py" and not path.name.startswith("__")
    } == {definition.path.name for definition in definitions}
    assert "Bake Cinematics" in labels
    assert any(definition.description for definition in definitions)


def test_available_script_files_matches_discovery() -> None:
    directory = get_script_library_path()

    available = available_script_files(directory)
    definitions = discover_unreal_scripts(directory)

    assert {path.name for path in available} == {
        definition.path.name for definition in definitions
    }


def test_deploy_unreal_resources(tmp_path: Path) -> None:
    destination = deploy_unreal_resources(tmp_path / "deploy")

    assert destination.exists()
    assert (destination / "menu.py").exists()
    scripts = [path.name for path in (destination / "scripts").glob("*.py")]
    assert "bake_cinematics.py" in scripts
