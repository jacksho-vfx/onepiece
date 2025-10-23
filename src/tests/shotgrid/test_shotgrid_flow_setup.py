# """Tests for the ShotGrid flow setup helpers."""
#
# from unittest.mock import MagicMock
#
# import pytest
#
# from libraries.integrations.shotgrid.api import ShotGridClient
# from libraries.integrations.shotgrid.flow_setup import setup_single_shot
# from libraries.integrations.shotgrid.models import EpisodeData, SceneData, ShotData
#
#
# @pytest.fixture
# def mock_client() -> MagicMock:
#     client = MagicMock(spec=ShotGridClient)
#     client.get_or_create_episode.return_value = {"id": 2}
#     client.get_or_create_scene.return_value = {"id": 3}
#     client.get_or_create_shot.return_value = {"id": 4}
#     return client
#
#
# def test_setup_single_shot_uses_existing_project(mock_client: MagicMock) -> None:
#     mock_client.get_project.return_value = {"id": 1}
#
#     setup_single_shot("Project X", "E01_S01_SH010", client=mock_client)
#
#     mock_client.get_project.assert_called_once_with("Project X")
#     mock_client.get_or_create_project.assert_not_called()
#
#     episode_data = mock_client.get_or_create_episode.call_args[0][0]
#     assert isinstance(episode_data, EpisodeData)
#     assert episode_data.code == "E01"
#     assert episode_data.project_id == 1
#
#     scene_data = mock_client.get_or_create_scene.call_args[0][0]
#     assert isinstance(scene_data, SceneData)
#     assert scene_data.code == "S01"
#     assert scene_data.project_id == 1
#     assert scene_data.episode_id == 2
#
#     shot_data = mock_client.get_or_create_shot.call_args[0][0]
#     assert isinstance(shot_data, ShotData)
#     assert shot_data.code == "E01_S01_SH010"
#     assert shot_data.project_id == 1
#     assert shot_data.scene_id == 3
#
#
# def test_setup_single_shot_creates_missing_project(mock_client: MagicMock) -> None:
#     mock_client.get_project.return_value = None
#     mock_client.get_or_create_project.return_value = {"id": 10}
#
#     setup_single_shot("Project Y", "E02_S02_SH020", client=mock_client)
#
#     mock_client.get_or_create_project.assert_called_once_with(
#         "Project Y", template=None
#     )
#
#     episode_data = mock_client.get_or_create_episode.call_args[0][0]
#     assert isinstance(episode_data, EpisodeData)
#     assert episode_data.project_id == 10
#
#     scene_data = mock_client.get_or_create_scene.call_args[0][0]
#     assert scene_data.project_id == 10
#
#     shot_data = mock_client.get_or_create_shot.call_args[0][0]
#     assert shot_data.project_id == 10
#
#
# def test_setup_single_shot_errors_when_project_unavailable(
#     mock_client: MagicMock,
# ) -> None:
#     mock_client.get_project.return_value = None
#     mock_client.get_or_create_project.return_value = None
#
#     with pytest.raises(RuntimeError, match="Project 'Missing' could not be retrieved"):
#         setup_single_shot("Missing", "E03_S03_SH030", client=mock_client)
#
#     mock_client.get_or_create_episode.assert_not_called()
#     mock_client.get_or_create_scene.assert_not_called()
#     mock_client.get_or_create_shot.assert_not_called()
