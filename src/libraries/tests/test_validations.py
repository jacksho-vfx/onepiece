from pathlib import Path

from libraries.validations import filesystem
from libraries.validations import naming


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
