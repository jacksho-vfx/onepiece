from pathlib import Path

from typer.testing import CliRunner

from apps.onepiece.dcc import max as max_cli
from libraries.creative.dcc.max import deploy


def test_available_scripts_returns_packaged_scripts() -> None:
    scripts = deploy.available_script_files()
    names = {script.name for script in scripts}

    assert {
        "cleanup_geometry.ms",
        "prep_render_layers.ms",
        "collect_textures.ms",
        "sync_shot_metadata.ms",
    }.issubset(names)


def test_deploy_max_resources_copies_payload(tmp_path: Path) -> None:
    destination = tmp_path / "max_payload"

    deployed = deploy.deploy_max_resources(destination)

    assert deployed == destination
    assert (destination / "menu.ms").exists()
    assert (destination / "scripts").is_dir()


def test_cli_deploy_reports_destination(tmp_path: Path) -> None:
    runner = CliRunner()
    destination = tmp_path / "cli_target"

    result = runner.invoke(
        max_cli.app, ["deploy", "--target", str(destination), "--overwrite"]
    )

    assert result.exit_code == 0
    assert destination.exists()
    assert "Deployed OnePiece 3ds Max panel" in result.stdout
