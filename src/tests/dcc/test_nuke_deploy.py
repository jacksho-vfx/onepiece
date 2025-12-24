from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from apps.onepiece.dcc import nuke as nuke_cli
from libraries.creative.dcc.nuke import deploy


def test_available_scripts_returns_packaged_scripts() -> None:
    scripts = deploy.available_script_files()
    names = {script.name for script in scripts}

    assert {
        "cleanup_backdrops.py",
        "refresh_reads.py",
        "generate_preview.py",
    }.issubset(names)


def test_deploy_nuke_resources_copies_payload(tmp_path: Path) -> None:
    destination = tmp_path / "nuke_payload"

    deployed = deploy.deploy_nuke_resources(destination)

    assert deployed == destination
    assert (destination / "menu.py").exists()
    assert (destination / "scripts").is_dir()


def test_cli_deploy_reports_destination(tmp_path: Path) -> None:
    runner = CliRunner()
    destination = tmp_path / "cli_target"

    result = runner.invoke(
        nuke_cli,
        ["deploy", "--target", str(destination), "--overwrite"],
    )

    assert result.exit_code == 0
    assert destination.exists()
    assert "Deployed OnePiece Nuke panel" in result.stdout
