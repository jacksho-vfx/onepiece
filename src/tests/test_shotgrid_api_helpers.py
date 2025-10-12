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
            "entity": {"data": {"name": "SHOT_010", "code": "SHOT_010_CODE"}}
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


def test_list_playlists_filters_by_project_and_paginates(
    client: ShotGridClient,
) -> None:
    client.base_url = "https://example.com"
    client.get_project = MagicMock(return_value={"id": 77})

    session = MagicMock()
    client._session = session

    page_one = MagicMock()
    page_one.ok = True
    page_one.status_code = 200
    page_one.text = ""
    page_one.json.return_value = {
        "data": [{"id": 1}, {"id": 2}],
        "links": {"next": "https://example.com/api/v1/entities/playlists?page[number]=2"},
    }

    page_two = MagicMock()
    page_two.ok = True
    page_two.status_code = 200
    page_two.text = ""
    page_two.json.return_value = {
        "data": [{"id": 3}],
        "links": {},
    }

    session.get.side_effect = [page_one, page_two]

    result = client.list_playlists("Project Name")

    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert session.get.call_count == 2

    first_call_kwargs = session.get.call_args_list[0].kwargs
    assert first_call_kwargs["params"]["filter[0][project]"] == 77
    assert first_call_kwargs["params"]["page[number]"] == 1

    second_call_kwargs = session.get.call_args_list[1].kwargs
    assert second_call_kwargs["params"]["page[number]"] == 2


def test_expand_playlist_versions_fetches_and_normalises(
    client: ShotGridClient,
) -> None:
    playlist = {
        "relationships": {
            "versions": {
                "data": [
                    {"id": 101},
                    {"id": "102"},
                    {"id": None},
                    "ignored",
                ]
            }
        }
    }

    version_payloads = [
        {
            "id": 101,
            "attributes": {
                "code": "shot010_v001",
                "version_number": 1,
                "sg_status_list": "rev",
                "sg_path_to_movie": "/movie.mov",
                "sg_uploaded_movie": None,
                "description": "First",
            },
            "relationships": {
                "entity": {"data": {"code": "SHOT_010"}},
                "project": {"data": {"id": 5}},
            },
        },
        {
            "id": 102,
            "attributes": {
                "code": "shot020_v002",
                "version_number": 2,
                "sg_status_list": None,
                "sg_path_to_movie": None,
                "sg_uploaded_movie": "/upload.mov",
                "description": None,
            },
            "relationships": {
                "entity": {"data": {"name": "SHOT_020"}},
                "project": {"data": {"id": 5}},
            },
        },
    ]

    client._get = MagicMock(return_value=version_payloads)

    result = client.expand_playlist_versions(playlist)

    assert result == [
        {
            "id": 101,
            "code": "shot010_v001",
            "shot": "SHOT_010",
            "version_number": 1,
            "file_path": "/movie.mov",
            "status": "rev",
            "description": "First",
            "project_id": 5,
        },
        {
            "id": 102,
            "code": "shot020_v002",
            "shot": "SHOT_020",
            "version_number": 2,
            "file_path": "/upload.mov",
            "status": None,
            "description": None,
            "project_id": 5,
        },
    ]

    assert client._get.call_count == 1
    entity, filters, fields = client._get.call_args.args
    assert entity == "Version"
    assert filters == [{"id[$in]": "101,102"}]
    assert "description" in fields
