"""Tests for :mod:`libraries.shotgrid.api` helper logic."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from libraries.shotgrid.api import ShotGridClient
from libraries.shotgrid.models import EpisodeData, SceneData, ShotData, VersionData


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


def test_get_version_builds_filters_and_normalises(client: ShotGridClient) -> None:
    version = VersionData(
        code="Shot010_V001",
        project_id=55,
        extra={
            "entity": {"data": {"type": "Shot", "id": 777, "code": "Shot010"}},
        },
    )

    record = {
        "id": 123,
        "attributes": {
            "code": "Shot010_V001",
            "version_number": 1,
            "sg_status_list": "rev",
            "sg_path_to_movie": "/path/to/movie.mov",
            "description": "A test",
        },
        "relationships": {
            "entity": {"data": {"type": "Shot", "id": 777, "name": "Shot010"}},
            "project": {"data": {"type": "Project", "id": 55}},
        },
    }

    captured: dict[str, object] = {}

    def fake_get(entity: str, filters: list[dict[str, object]], fields: str) -> list[dict[str, object]]:
        captured.update({"entity": entity, "filters": filters, "fields": fields})
        return [record]

    client._get = fake_get  # type: ignore[assignment]

    result = client.get_version(version)

    assert captured["entity"] == "Version"
    assert captured["fields"] == (
        "code,version_number,sg_status_list,sg_path_to_movie,sg_uploaded_movie,description,entity,project"
    )
    assert captured["filters"] == [
        {"code": "Shot010_V001"},
        {"project.id[$eq]": 55},
        {"entity.Shot.id[$eq]": 777},
        {"entity.Shot.code[$eq]": "Shot010"},
    ]
    assert result == {
        "id": 123,
        "code": "Shot010_V001",
        "shot": "Shot010",
        "version_number": 1,
        "file_path": "/path/to/movie.mov",
        "status": "rev",
        "description": "A test",
        "project_id": 55,
    }


def test_get_version_returns_none_when_missing(client: ShotGridClient) -> None:
    version = VersionData(code="Missing", project_id=44)

    def fake_get(entity: str, filters: list[dict[str, object]], fields: str) -> list[dict[str, object]]:
        return []

    client._get = fake_get  # type: ignore[assignment]

    result = client.get_version(version)

    assert result is None


def test_get_version_requires_filters(client: ShotGridClient) -> None:
    version = VersionData()

    with pytest.raises(ValueError):
        client.get_version(version)
