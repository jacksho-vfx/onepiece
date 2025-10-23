"""Tests for the ShotGrid upload-version CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.onepiece.utils.errors import OnePieceValidationError
from libraries.shotgrid.api import ShotGridClient
from libraries.shotgrid.models import VersionData


class StubShotGridClient:
    """Stub ShotGrid client used to capture upload interactions."""

    def __init__(
        self, project: dict[str, object], shot: dict[str, object] | None = None
    ) -> None:
        self._project = project
        self._shot = shot or {"id": 101, "code": "shot", "type": "Shot"}
        self.version_payload: dict[str, object] | None = None
        self.get_shot_args: tuple[object, object] | None = None
        self.media_path: Path | None = None

    def get_project(self, project_name: str) -> dict[str, object]:
        return self._project

    def get_shot(self, project_id: int, shot_name: str) -> dict[str, object] | None:
        self.get_shot_args = (project_id, shot_name)
        return self._shot

    def create_version(self, version_data: object) -> dict[str, object]:
        self.version_payload = {"data": version_data}
        return {"id": 999}

    def create_version_with_media(
        self, version_data: object, media_path: Path
    ) -> dict[str, object]:
        self.version_payload = {"data": version_data}
        self.media_path = media_path
        return {"id": 999}


def _make_media_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "clip.mov"
    file_path.write_bytes(b"data")
    return file_path


def test_upload_uses_project_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = __import__("apps.onepiece.shotgrid.upload_version", fromlist=["upload"])

    stub = StubShotGridClient({"id": 55, "name": "Test"})
    monkeypatch.setattr(module, "ShotGridClient", lambda: stub)

    module.upload(
        project_name="Demo", shot_name="Shot010", file_path=_make_media_file(tmp_path)
    )

    assert stub.get_shot_args == (55, "Shot010")


def test_upload_sets_entity_relationship(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = __import__("apps.onepiece.shotgrid.upload_version", fromlist=["upload"])

    shot = {"id": 777, "code": "Shot020", "type": "Shot"}
    stub = StubShotGridClient({"id": 55, "name": "Test"}, shot=shot)
    monkeypatch.setattr(module, "ShotGridClient", lambda: stub)

    module.upload(
        project_name="Demo", shot_name="Shot020", file_path=_make_media_file(tmp_path)
    )

    assert stub.version_payload is not None
    version_data = stub.version_payload["data"]
    assert version_data.extra["entity"] == {"data": {"type": "Shot", "id": 777}}  # type: ignore[attr-defined]


def test_upload_missing_project_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = __import__("apps.onepiece.shotgrid.upload_version", fromlist=["upload"])

    stub = StubShotGridClient({"id": "", "name": "Test"})
    monkeypatch.setattr(module, "ShotGridClient", lambda: stub)

    with pytest.raises(OnePieceValidationError) as excinfo:
        module.upload(
            project_name="Demo",
            shot_name="Shot010",
            file_path=_make_media_file(tmp_path),
        )

    assert "missing an ID" in str(excinfo.value)
    assert stub.get_shot_args is None


def test_create_version_merges_entity_relationship() -> None:
    client = ShotGridClient.__new__(ShotGridClient)
    captured: dict[str, object] = {}

    def fake_post(
        entity: str,
        attributes: dict[str, object],
        relationships: dict[str, object] | None = None,
    ) -> dict[str, object]:
        captured.update(
            {
                "entity": entity,
                "attributes": attributes,
                "relationships": relationships or {},
            }
        )
        return {"id": 1}

    client._post = fake_post

    version = VersionData(
        code="Shot020_V001",
        project_id=55,
        extra={
            "description": "A test version",
            "entity": {"data": {"type": "Shot", "id": 777}},
        },
    )

    client.create_version(version)

    assert captured["entity"] == "Version"
    assert captured["attributes"] == {
        "code": "Shot020_V001",
        "description": "A test version",
    }
    relationships = captured["relationships"]
    assert relationships == {
        "project": {"data": {"type": "Project", "id": 55}},
        "entity": {"data": {"type": "Shot", "id": 777}},
    }
