"""Tests for :mod:`libraries.shotgrid.api` helper logic."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from libraries.shotgrid.api import ShotGridClient
from libraries.shotgrid.models import EpisodeData, SceneData, ShotData


@pytest.fixture()
def client() -> ShotGridClient:
    """Return an uninitialised ``ShotGridClient`` for isolated testing."""

    return ShotGridClient.__new__(ShotGridClient)


def test_get_or_create_episode_returns_existing(client: ShotGridClient) -> None:
    data = EpisodeData(code="EP01", project_id=101)
    episode = {"id": 11, "code": "EP01"}

    client.get_episode = MagicMock(return_value=episode)
    client.create_episode = MagicMock()

    result = client.get_or_create_episode(data)

    assert result == episode
    client.create_episode.assert_not_called()


def test_get_or_create_project_creates_when_missing(client: ShotGridClient) -> None:
    client.get_project = MagicMock(return_value=None)
    created = {"id": 5, "name": "New Project"}
    client.create_project = MagicMock(return_value=created)

    result = client.get_or_create_project("New Project", template=None)

    assert result == created


def test_get_or_create_episode_skips_creation_without_identifiers(
    client: ShotGridClient,
) -> None:
    data = EpisodeData(code=None, project_id=42)

    client.get_episode = MagicMock(side_effect=AssertionError("should not fetch"))
    client.create_episode = MagicMock(side_effect=AssertionError("should not create"))

    result = client.get_or_create_episode(data)

    assert result is None


def test_get_or_create_scene_creates_when_missing(client: ShotGridClient) -> None:
    data = SceneData(code="EP01_SC01", project_id=202)
    created = {"id": 22, "code": "EP01_SC01"}

    client.get_scene = MagicMock(return_value=None)
    client.create_scene = MagicMock(return_value=created)

    result = client.get_or_create_scene(data)

    assert result == created


def test_get_or_create_shot_skips_creation_without_identifiers(
    client: ShotGridClient,
) -> None:
    data = ShotData(code="", project_id=303)

    client.get_shot = MagicMock(side_effect=AssertionError("should not fetch"))
    client.create_shot = MagicMock(side_effect=AssertionError("should not create"))

    result = client.get_or_create_shot(data)

    assert result is None


def test_simplify_version_record_prefers_entity_name(client: ShotGridClient) -> None:
    record = {
        "attributes": {
            "code": "shot010_v001",
            "version_number": 1,
            "sg_path_to_movie": "/path/to/movie.mov",
            "sg_status_list": "rev",
        },
        "relationships": {
            "entity": {
                "data": {"name": "SHOT_010", "code": "SHOT_010_CODE"}
            }
        },
    }

    result = client._simplify_version_record(record)

    assert result == {
        "shot": "SHOT_010",
        "version_number": 1,
        "file_path": "/path/to/movie.mov",
        "status": "rev",
        "code": "shot010_v001",
    }


def test_simplify_version_record_falls_back_to_uploaded_media(
    client: ShotGridClient,
) -> None:
    record = {
        "attributes": {
            "code": "shot020_v002",
            "version_number": 2,
            "sg_path_to_movie": None,
            "sg_uploaded_movie": "/upload/movie.mov",
            "sg_status_list": None,
        },
        "relationships": {"entity": {"data": {}}},
    }

    result = client._simplify_version_record(record)

    assert result == {
        "shot": "shot020_v002",
        "version_number": 2,
        "file_path": "/upload/movie.mov",
        "status": None,
        "code": "shot020_v002",
    }
