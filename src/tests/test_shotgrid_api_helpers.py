"""Tests for :mod:`libraries.shotgrid.api` helper logic."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from libraries.shotgrid.api import ShotGridClient, ShotGridError, _version_view
from libraries.shotgrid.models import EpisodeData, SceneData, ShotData


@pytest.fixture()
def client() -> ShotGridClient:
    """Return an uninitialised ``ShotGridClient`` for isolated testing."""

    return ShotGridClient.__new__(ShotGridClient)


class StubResponse:
    def __init__(
        self,
        *,
        ok: bool,
        status_code: int = 200,
        text: str = "",
        payload: dict | None = None,
    ) -> None:
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class StubSession:
    def __init__(self, response: StubResponse) -> None:
        self._response = response
        self.patch_calls: list[tuple[str, dict]] = []

    def patch(self, url: str, *, json: dict) -> StubResponse:
        self.patch_calls.append((url, json))
        return self._response


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


def test_update_version_sends_patch_request(client: ShotGridClient) -> None:
    client.base_url = "https://example.com"
    response_payload = {"data": {"id": 123, "type": "Version"}}
    session = StubSession(StubResponse(ok=True, payload=response_payload))
    client._session = session

    result = client.update_version(123, {"description": "Updated"})

    assert result == response_payload["data"]
    assert len(session.patch_calls) == 1

    url, payload = session.patch_calls[0]
    assert url == "https://example.com/api/v1/entity/versions/123"
    assert payload == {
        "data": {
            "type": "Version",
            "id": 123,
            "attributes": {"description": "Updated"},
        }
    }


def test_update_version_includes_relationships(client: ShotGridClient) -> None:
    client.base_url = "https://shotgrid.example"
    response_payload = {"data": {"id": 55}}
    session = StubSession(StubResponse(ok=True, payload=response_payload))
    client._session = session

    relationships = {"project": {"data": {"type": "Project", "id": 42}}}
    client.update_version(55, {"code": "shot030_v001"}, relationships)

    _, payload = session.patch_calls[0]
    assert payload["data"]["relationships"] == relationships


def test_update_version_status_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ShotGridClient.__new__(ShotGridClient)
    captured: dict[str, tuple[int, dict, dict | None]] = {}

    def fake_update(
        version_id: int,
        attributes: dict,
        relationships: dict | None = None,
    ) -> None:
        captured["call"] = (version_id, attributes, relationships)

    monkeypatch.setattr(client, "update_version", fake_update)

    client.update_version_status(999, "apr")

    assert captured["call"] == (999, {"sg_status_list": "apr"}, None)


def test_update_version_raises_on_error(
    client: ShotGridClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.base_url = "https://example.com"
    response = StubResponse(ok=False, status_code=404, text="Not Found")
    session = StubSession(response)
    client._session = session

    log_error = MagicMock()
    monkeypatch.setattr("libraries.shotgrid.api.log.error", log_error)

    with pytest.raises(ShotGridError) as excinfo:
        client.update_version(321, {"description": "Missing"})

    assert "PATCH Version 321 failed" in str(excinfo.value)

    log_error.assert_called_once_with(
        "http_patch_failed",
        entity="Version",
        entity_id=321,
        status=404,
        text="Not Found",
    )


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
        "links": {
            "next": "https://example.com/api/v1/entities/playlists?page[number]=2"
        },
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
    assert fields.split(",") == _version_view(summary=False)[0]


def test_version_view_summary_fields_and_parser() -> None:
    fields, parser = _version_view(summary=True)

    assert fields == [
        "code",
        "version_number",
        "sg_status_list",
        "sg_path_to_movie",
        "sg_uploaded_movie",
        "entity",
    ]

    record = {
        "id": 55,
        "attributes": {
            "code": "shot030_v003",
            "version_number": 3,
            "sg_status_list": "apr",
            "sg_path_to_movie": None,
            "sg_uploaded_movie": "/path/to/upload.mov",
            "description": "Irrelevant",
        },
        "relationships": {
            "entity": {"data": {"name": "SHOT_030", "code": "SHOT_030_CODE"}},
            "project": {"data": {"id": 9}},
        },
    }

    assert parser(record) == {
        "shot": "SHOT_030",
        "version_number": 3,
        "file_path": "/path/to/upload.mov",
        "status": "apr",
        "code": "shot030_v003",
    }


def test_version_view_full_fields_and_parser() -> None:
    fields, parser = _version_view(summary=False)

    assert fields == [
        "code",
        "version_number",
        "sg_status_list",
        "sg_path_to_movie",
        "sg_uploaded_movie",
        "entity",
        "description",
        "project",
    ]

    record = {
        "id": 88,
        "attributes": {
            "code": "shot040_v004",
            "version_number": 4,
            "sg_status_list": "wtg",
            "sg_path_to_movie": "/movie.mov",
            "sg_uploaded_movie": None,
            "description": "Waiting for notes",
        },
        "relationships": {
            "entity": {"data": {"code": "SHOT_040"}},
            "project": {"data": {"id": 42}},
        },
    }

    assert parser(record) == {
        "id": 88,
        "code": "shot040_v004",
        "shot": "SHOT_040",
        "version_number": 4,
        "file_path": "/movie.mov",
        "status": "wtg",
        "description": "Waiting for notes",
        "project_id": 42,
    }
