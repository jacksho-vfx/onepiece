from pathlib import Path

from unittest.mock import patch, MagicMock

from libraries.validations import filesystem
from libraries.validations import naming
from libraries.validations import dcc as dcc_validations
from libraries.dcc.dcc_client import SupportedDCC


# ---------- Filesystem ----------


def test_check_paths(tmp_path: Path) -> None:
    dir_path = tmp_path / "renders"
    dir_path.mkdir()
    results = filesystem.check_paths([dir_path])
    assert results[str(dir_path)]["exists"]
    assert results[str(dir_path)]["writable"] is True


def test_preflight_report(tmp_path: Path) -> None:
    dir_path = tmp_path / "renders"
    dir_path.mkdir()
    assert filesystem.preflight_report([dir_path]) is True


# ---------- Naming ----------


def test_validate_show_name() -> None:
    assert naming.validate_show_name("blob01")
    assert naming.validate_show_name("frog99")
    assert not naming.validate_show_name("01frog")
    assert not naming.validate_show_name("frog")


def test_validate_episode_scene_shot_names() -> None:
    assert naming.validate_episode_name("ep101")
    assert naming.validate_scene_name("sc01")
    assert naming.validate_shot("0010")
    assert naming.validate_shot_name("ep101_sc01_0010")
    assert naming.validate_asset_name("ep101_sc01_0010_asset")
    assert not naming.validate_asset_name("ep101_sc01_0010-asset")


@patch("libraries.validations.dcc.shutil.which", return_value="/opt/Nuke14/Nuke14.0")
def test_check_dcc_environment_reports_missing_plugins(mock_which: MagicMock) -> None:
    env = {
        "PATH": "/opt/Nuke14",
        "ONEPIECE_NUKE_PLUGINS": "CaraVR",
        "ONEPIECE_NUKE_GPU": "NVIDIA RTX (OpenGL 4.1)",
    }

    report = dcc_validations.check_dcc_environment(SupportedDCC.NUKE, env=env)

    assert report.installed is True
    assert report.executable == "/opt/Nuke14/Nuke14.0"
    assert report.plugins.missing == frozenset({"OCIO"})
    assert report.gpu.meets_requirement is True


@patch("libraries.validations.dcc.shutil.which", return_value=None)
def test_check_dcc_environment_missing_gpu(mock_which: MagicMock) -> None:
    report = dcc_validations.check_dcc_environment(
        SupportedDCC.MAYA,
        env={},
        plugin_inventory={SupportedDCC.MAYA: frozenset({"mtoa", "bifrost"})},
        gpu_info={SupportedDCC.MAYA: None},
    )

    assert report.installed is False
    assert report.plugins.missing == frozenset()
    assert report.gpu.meets_requirement is False
