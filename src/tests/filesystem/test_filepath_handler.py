"""Tests for the default filepath handler helpers."""

from pathlib import Path

from libraries.platform.handlers.filepath_handler import FilepathHandler


def test_filepath_handler_creates_expected_directories(tmp_path: Path) -> None:
    handler = FilepathHandler(root=tmp_path)

    project = handler.get_project_dir("DemoProject")
    episode = handler.get_episode_dir("DemoProject", "EP01")
    sequence = handler.get_sequence_dir("DemoProject", "EP01", "SEQ010")
    scene = handler.get_scene_dir("DemoProject", "EP01", "SEQ010")
    shot = handler.get_shot_dir("DemoProject", "EP01", "SEQ010", "SH010")
    media = handler.get_original_media_dir("DemoProject")

    assert project == tmp_path / "projects" / "DemoProject"
    assert episode == project / "episodes" / "EP01"
    assert sequence == episode / "scenes" / "SEQ010"
    assert scene == sequence
    assert shot == sequence / "shots" / "SH010"
    assert media == project / "media" / "original"

    for path in (project, episode, sequence, scene, shot, media):
        assert path.exists()
