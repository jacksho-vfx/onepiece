from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from libraries.integrations.mudstack.api import MudstackClient, MudstackError
from libraries.integrations.mudstack.config import load_config
from libraries.integrations.mudstack.models import ProjectData


def test_load_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEPIECE_MUDSTACK_URL", "https://mud.example")
    monkeypatch.setenv("ONEPIECE_MUDSTACK_API_KEY", "secret")
    monkeypatch.setenv("ONEPIECE_MUDSTACK_WORKSPACE", "studio")

    cfg = load_config()

    assert cfg.base_url == "https://mud.example"
    assert cfg.api_key == "secret"
    assert cfg.workspace == "studio"


class DummyResponse(SimpleNamespace):
    def __init__(
        self, json_data: object, status_code: int = 200, text: str = ""
    ) -> None:
        super().__init__(json=lambda: json_data, status_code=status_code, text=text)
        self.ok = status_code < 400


def test_create_project_posts_expected_payload(mocker: MockerFixture) -> None:
    mock_request = mocker.patch(
        "requests.Session.request", return_value=DummyResponse({"data": {"id": "1"}})
    )

    client = MudstackClient(base_url="https://mud.example", api_key="token")
    project = client.create_project(ProjectData(name="Example", code="EX"))

    assert project == {"id": "1"}

    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "post"
    assert kwargs["url"] == "https://mud.example/api/v1/projects"
    assert kwargs["json"] == {
        "name": "Example",
        "code": "EX",
        "tags": [],
        "metadata": {},
    }

    assert client._session.headers["Authorization"] == "Bearer token"


def test_request_failure_raises_error(mocker: MockerFixture) -> None:
    mocker.patch(
        "requests.Session.request",
        return_value=DummyResponse({"error": "nope"}, status_code=500, text="nope"),
    )
    client = MudstackClient(base_url="https://mud.example", api_key="token")

    with pytest.raises(MudstackError):
        client.list_projects()


def test_upload_media_uses_binary_payload(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    media = tmp_path / "clip.mov"
    media.write_bytes(b"data")

    mock_request = mocker.patch(
        "requests.Session.request",
        return_value=DummyResponse({"data": {"stored": True}}),
    )

    client = MudstackClient(base_url="https://mud.example", api_key="token")
    result = client.upload_media("assets", "asset-1", media)

    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "post"
    assert kwargs["url"] == "https://mud.example/api/v1/assets/asset-1/upload"
    assert "media" in kwargs["files"]
    assert kwargs["files"]["media"][0] == "clip.mov"
    assert result == {"stored": True}
