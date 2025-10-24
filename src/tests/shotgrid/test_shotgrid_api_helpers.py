"""Tests for :mod:`libraries.integrations.shotgrid.api` helper logic."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from libraries.integrations.shotgrid.api import (
    ShotGridClient,
    ShotGridError,
    _version_view,
)
from libraries.integrations.shotgrid.models import (
    EpisodeData,
    PlaylistData,
    PipelineStep,
    SceneData,
    ShotData,
    TaskCode,
    TaskData,
)


@pytest.fixture()
def client() -> ShotGridClient:
    """Return an uninitialised ``ShotGridClient`` for isolated testing."""

    instance = ShotGridClient.__new__(ShotGridClient)
    instance.timeout = ShotGridClient.DEFAULT_TIMEOUT
    return instance


class StubResponse:
    def __init__(
        self,
        *,
        ok: bool,
        status_code: int = 200,
        text: str = "",
        payload: dict[Any, Any] | None = None,
    ) -> None:
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self) -> dict[Any, Any]:
        return self._payload


class StubSession:
    def __init__(self, response: StubResponse) -> None:
        self._response = response
        self.patch_calls: list[tuple[str, dict[Any, Any], object | None]] = []

    def patch(
        self, url: str, *, json: dict[Any, Any], timeout: object | None = None
    ) -> StubResponse:
        self.patch_calls.append((url, json, timeout))
        return self._response


def test_authenticate_uses_configured_timeout(
    client: ShotGridClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.base_url = "https://example.com"
    session = MagicMock()
    session.headers = {}
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"access_token": "token"}
    session.post.return_value = response
    client._session = session

    client._authenticate("script", "key")

    assert session.post.call_args.kwargs["timeout"] == client.timeout


def test_get_uses_configured_timeout(client: ShotGridClient) -> None:
    client.base_url = "https://example.com"
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"data": []}
    session.get.return_value = response
    client._session = session

    client._get("Shot", [], "id")

    assert session.get.call_args.kwargs["timeout"] == client.timeout


def test_get_single_limits_page_size_and_returns_none(
    client: ShotGridClient,
) -> None:
    client.base_url = "https://example.com"
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"data": []}
    session.get.return_value = response
    client._session = session

    result = client._get_single("Shot", [], "id")

    assert result is None
    params = session.get.call_args.kwargs["params"]
    assert params["page[size]"] == 1


def test_get_paginated_honours_timeout(client: ShotGridClient) -> None:
    client.base_url = "https://example.com"
    session = MagicMock()
    page_one = MagicMock()
    page_one.ok = True
    page_one.json.return_value = {
        "data": [],
        "links": {"next": "ignored"},
    }
    page_two = MagicMock()
    page_two.ok = True
    page_two.json.return_value = {
        "data": [],
        "links": {},
    }
    session.get.side_effect = [page_one, page_two]
    client._session = session

    client._get_paginated("Playlist", [], "id")

    assert session.get.call_count == 2
    for call in session.get.call_args_list:
        assert call.kwargs["timeout"] == client.timeout


def test_post_uses_configured_timeout(client: ShotGridClient) -> None:
    client.base_url = "https://example.com"
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"data": {"id": 1}}
    session.post.return_value = response
    client._session = session

    client._post("Shot", {"code": "SHOT"})

    assert session.post.call_args.kwargs["timeout"] == client.timeout


def test_upload_media_uses_configured_timeout(
    client: ShotGridClient, tmp_path: Path
) -> None:
    client.base_url = "https://example.com"
    media = tmp_path / "clip.mov"
    media.write_bytes(b"data")
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"status": "ok"}
    session.post.return_value = response
    client._session = session

    client.upload_media("Version", 101, media)

    assert session.post.call_args.kwargs["timeout"] == client.timeout


def test_init_applies_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(
        base_url="https://example.com", script_name="script", api_key="key"
    )
    monkeypatch.setattr("libraries.integrations.shotgrid.api.load_config", lambda: cfg)

    captured: dict[str, tuple[str, str]] = {}

    def fake_authenticate(self: ShotGridClient, script: str, key: str) -> None:
        captured["args"] = (script, key)

    monkeypatch.setattr(ShotGridClient, "_authenticate", fake_authenticate)

    client = ShotGridClient()

    assert client.timeout == ShotGridClient.DEFAULT_TIMEOUT
    assert captured["args"] == (cfg.script_name, cfg.api_key)


def test_init_accepts_custom_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(
        base_url="https://example.com", script_name="script", api_key="key"
    )
    monkeypatch.setattr("libraries.integrations.shotgrid.api.load_config", lambda: cfg)

    def fake_authenticate(self: ShotGridClient, script: str, key: str) -> None:
        return None

    monkeypatch.setattr(ShotGridClient, "_authenticate", fake_authenticate)

    client = ShotGridClient(timeout=5.5)

    assert client.timeout == 5.5


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


def test_create_project_sets_name_and_code(client: ShotGridClient) -> None:
    client._post = MagicMock(return_value={"id": 42})

    result = client.create_project("Project X", template="episodic")

    assert result == {"id": 42}
    entity_type, attributes = client._post.call_args.args[:2]
    assert entity_type == "Project"
    assert attributes == {
        "name": "Project X",
        "code": "Project X",
        "template": "episodic",
    }


def test_create_project_omits_template_when_none(client: ShotGridClient) -> None:
    client._post = MagicMock(return_value={"id": 99})

    client.create_project("Project Y", template=None)

    entity_type, attributes = client._post.call_args.args[:2]
    assert entity_type == "Project"
    assert attributes == {"name": "Project Y", "code": "Project Y"}


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

    url, payload, timeout = session.patch_calls[0]
    assert url == "https://example.com/api/v1/entity/versions/123"
    assert payload == {
        "data": {
            "type": "Version",
            "id": 123,
            "attributes": {"description": "Updated"},
        }
    }
    assert timeout == client.timeout


def test_update_version_includes_relationships(client: ShotGridClient) -> None:
    client.base_url = "https://shotgrid.example"
    response_payload = {"data": {"id": 55}}
    session = StubSession(StubResponse(ok=True, payload=response_payload))
    client._session = session

    relationships = {"project": {"data": {"type": "Project", "id": 42}}}
    client.update_version(55, {"code": "shot030_v001"}, relationships)

    _, payload, timeout = session.patch_calls[0]
    assert payload["data"]["relationships"] == relationships
    assert timeout == client.timeout


def test_create_playlist_includes_version_relationships(
    client: ShotGridClient,
) -> None:
    data = PlaylistData(
        code="Dailies",
        project_id=321,
        version_ids=[11, 22],
    )
    client._post = MagicMock(return_value={"id": 99})

    result = client.create_playlist(data)

    assert result == {"id": 99}
    entity_type, attributes, relationships = client._post.call_args.args
    assert entity_type == "Playlist"
    assert attributes == {"code": "Dailies"}
    assert relationships["project"] == {"data": {"type": "Project", "id": 321}}
    assert relationships["versions"] == {
        "data": [
            {"type": "Version", "id": 11},
            {"type": "Version", "id": 22},
        ]
    }


def test_create_task_includes_entity_relationship(client: ShotGridClient) -> None:
    data = TaskData(
        project_id=101,
        entity_id=202,
        related_entity_type="Asset",
        code=TaskCode.FINAL_DELIVERY,
    )
    client._get_single = MagicMock(return_value={"id": 5, "code": "Comp"})
    client._post = MagicMock(return_value={"id": 77})

    result = client.create_task(data, PipelineStep.COMP)

    assert result == {"id": 77}
    entity_type, attributes, relationships = client._post.call_args.args
    assert entity_type == "Task"
    assert attributes["code"] == TaskCode.FINAL_DELIVERY.value
    assert attributes["content"] == TaskCode.FINAL_DELIVERY.value
    assert relationships["project"] == {"data": {"type": "Project", "id": 101}}
    assert relationships["entity"] == {"data": {"type": "Asset", "id": 202}}
    assert relationships["step"] == {"data": {"type": "Step", "id": 5}}


def test_create_task_defaults_related_entity_type(client: ShotGridClient) -> None:
    data = TaskData(project_id=303, entity_id=404)
    client._get_single = MagicMock(return_value={"id": 9, "code": "Lighting"})
    client._post = MagicMock(return_value={"id": 88})

    client.create_task(data, PipelineStep.LIGHTING)

    _, attributes, relationships = client._post.call_args.args
    assert attributes == {}
    assert relationships["project"] == {"data": {"type": "Project", "id": 303}}
    assert relationships["entity"] == {"data": {"type": "Shot", "id": 404}}
    assert relationships["step"] == {"data": {"type": "Step", "id": 9}}


def test_create_task_without_step_omits_relationship(client: ShotGridClient) -> None:
    data = TaskData(project_id=505)
    client._get_single = MagicMock()
    client._post = MagicMock(return_value={"id": 66})

    client.create_task(data, None)

    client._get_single.assert_not_called()
    _, attributes, relationships = client._post.call_args.args
    assert attributes == {}
    assert relationships["project"] == {"data": {"type": "Project", "id": 505}}
    assert "step" not in relationships


def test_update_version_status_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ShotGridClient.__new__(ShotGridClient)
    client.timeout = ShotGridClient.DEFAULT_TIMEOUT
    captured: dict[str, tuple[int, dict[Any, Any], dict[Any, Any] | None]] = {}

    def fake_update(
        version_id: int,
        attributes: dict[Any, Any],
        relationships: dict[Any, Any] | None = None,
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
    monkeypatch.setattr("libraries.integrations.shotgrid.api.log.error", log_error)

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


def test_list_playlists_returns_empty_when_project_missing(
    client: ShotGridClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.base_url = "https://example.com"
    client.get_project = MagicMock(return_value=None)

    session = MagicMock()
    client._session = session

    log_info = MagicMock()
    monkeypatch.setattr("libraries.integrations.shotgrid.api.log.info", log_info)

    result = client.list_playlists("Unknown Project")

    assert result == []
    session.get.assert_not_called()
    log_info.assert_called_once_with(
        "sg.list_playlists.project_missing", project="Unknown Project"
    )


def test_get_playlist_record_delegates_to_single(client: ShotGridClient) -> None:
    filters = [{"project": 77}, {"code": "Editorial"}]

    client._get_single = MagicMock(return_value={"id": 5})

    result = client.get_playlist_record(filters)

    assert result == {"id": 5}
    client._get_single.assert_called_once_with(
        "Playlist", filters, "id,name,code,versions"
    )


def test_get_playlist_record_accepts_sequence_fields(client: ShotGridClient) -> None:
    filters: list[dict[str, Any]] = []
    client._get_single = MagicMock(return_value=None)

    client.get_playlist_record(filters, ["id", "code"])

    client._get_single.assert_called_once_with("Playlist", filters, "id,code")


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

    client.list_versions_raw = MagicMock(return_value=version_payloads)

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


def test_expand_playlist_versions_respects_playlist_order(
    client: ShotGridClient,
) -> None:
    playlist = {
        "relationships": {
            "versions": {
                "data": [
                    {"id": 201},
                    {"id": 202},
                ]
            }
        }
    }

    version_payloads = [
        {
            "id": 202,
            "attributes": {
                "code": "shot020_v001",
                "version_number": 1,
                "sg_status_list": "rev",
                "sg_path_to_movie": None,
                "sg_uploaded_movie": "/movie.mov",
                "description": "Second",
            },
            "relationships": {
                "entity": {"data": {"code": "SHOT_020"}},
                "project": {"data": {"id": 7}},
            },
        },
        {
            "id": 201,
            "attributes": {
                "code": "shot010_v001",
                "version_number": 1,
                "sg_status_list": "apr",
                "sg_path_to_movie": "/movie.mov",
                "sg_uploaded_movie": None,
                "description": "First",
            },
            "relationships": {
                "entity": {"data": {"code": "SHOT_010"}},
                "project": {"data": {"id": 7}},
            },
        },
    ]

    client.list_versions_raw = MagicMock(return_value=version_payloads)

    result = client.expand_playlist_versions(playlist)

    assert [version["id"] for version in result] == [201, 202]

    assert client.list_versions_raw.call_count == 1
    filters, fields = client.list_versions_raw.call_args.args
    kwargs = client.list_versions_raw.call_args.kwargs
    assert filters == [{"id[$in]": "201,202"}]
    assert fields == _version_view(summary=False)[0]
    assert kwargs == {"page_size": None}


def test_list_versions_raw_uses_pagination_by_default(
    client: ShotGridClient,
) -> None:
    filters = [{"project": 99}]
    fields = ["code", "version_number"]

    client._get = MagicMock(side_effect=AssertionError("_get should not be used"))
    client._get_paginated = MagicMock(return_value=[{"id": 1}])

    result = client.list_versions_raw(filters, fields)

    assert result == [{"id": 1}]
    client._get_paginated.assert_called_once_with(
        "Version", filters, "code,version_number", page_size=100
    )


def test_list_versions_raw_supports_single_page_requests(
    client: ShotGridClient,
) -> None:
    default_fields = _version_view(summary=False)[0]

    client._get_paginated = MagicMock(
        side_effect=AssertionError("_get_paginated should not be used")
    )
    client._get = MagicMock(return_value=[{"id": 2}])

    result = client.list_versions_raw(None, None, page_size=None)

    assert result == [{"id": 2}]
    client._get.assert_called_once_with("Version", [], ",".join(default_fields))


def test_list_versions_raw_normalises_string_fields(
    client: ShotGridClient,
) -> None:
    client._get_paginated = MagicMock(return_value=[{"id": 3}])

    result = client.list_versions_raw([], " code , version_number ")

    assert result == [{"id": 3}]
    client._get_paginated.assert_called_once_with(
        "Version", [], "code,version_number", page_size=100
    )


def test_get_versions_for_project_aggregates_paginated_results(
    client: ShotGridClient,
) -> None:
    client.base_url = "https://example.com"
    client.get_project = MagicMock(return_value={"id": 42})

    def _record(index: int) -> dict[str, Any]:
        return {
            "id": index,
            "attributes": {
                "code": f"shot{index:03}_v001",
                "version_number": index,
                "sg_status_list": "rev",
                "sg_path_to_movie": f"/movie_{index}.mov",
                "sg_uploaded_movie": None,
            },
            "relationships": {
                "entity": {"data": {"name": f"SHOT_{index:03}"}},
                "project": {"data": {"id": 42}},
            },
        }

    first_page = StubResponse(
        ok=True,
        payload={
            "data": [_record(index) for index in range(1, 101)],
            "links": {"next": "token"},
        },
    )
    second_page = StubResponse(
        ok=True,
        payload={
            "data": [_record(index) for index in range(101, 151)],
            "links": {},
        },
    )

    session = MagicMock()
    session.get.side_effect = [first_page, second_page]
    client._session = session

    versions = client.get_versions_for_project("Project X")

    assert len(versions) == 150
    assert versions[0]["shot"] == "SHOT_001"
    assert versions[-1]["code"] == "shot150_v001"

    assert session.get.call_count == 2
    first_params = session.get.call_args_list[0].kwargs["params"]
    second_params = session.get.call_args_list[1].kwargs["params"]
    assert first_params["filter[0][project]"] == 42
    assert first_params["page[number]"] == 1
    assert first_params["page[size]"] == 100
    assert second_params["page[number]"] == 2
    assert second_params["page[size]"] == 100


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
