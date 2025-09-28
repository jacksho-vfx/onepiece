"""Tests for the ShotGrid bulk CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.apps.onepiece.shotgrid import delivery as shotgrid_cli


class StubShotgridClient:
    """Record calls made by the bulk CLI for verification."""

    def __init__(self) -> None:
        self.created: list[tuple[str, list[dict[str, object]]]] = []
        self.updated: list[tuple[str, list[dict[str, object]]]] = []
        self.deleted: list[tuple[str, list[int]]] = []

    def bulk_create_entities(self, entity_type: str, payloads: list[dict[str, object]]):
        payload_list = list(payloads)
        self.created.append((entity_type, payload_list))
        return [
            {"id": index + 1, **payload}
            for index, payload in enumerate(payload_list)
        ]

    def bulk_update_entities(self, entity_type: str, payloads: list[dict[str, object]]):
        payload_list = list(payloads)
        self.updated.append((entity_type, payload_list))
        return payload_list

    def bulk_delete_entities(self, entity_type: str, entity_ids: list[int]) -> None:
        ids = [int(entity_id) for entity_id in entity_ids]
        self.deleted.append((entity_type, ids))


runner = CliRunner()


def _write_json(tmp_path: Path, name: str, data: object) -> Path:
    file_path = tmp_path / name
    file_path.write_text(json.dumps(data))
    return file_path


def _parse_summary(output: str) -> dict[str, object]:
    start = output.find("{")
    assert start != -1, output
    return json.loads(output[start:])


def test_bulk_playlists_create_uses_payload_file(monkeypatch, tmp_path: Path) -> None:
    stub = StubShotgridClient()
    monkeypatch.setattr(shotgrid_cli, "ShotgridClient", lambda: stub)

    payload_file = _write_json(
        tmp_path,
        "playlists.json",
        [
            {"playlist_name": "Client Review", "project_id": 7},
            {"playlist_name": "Vendor Review", "project_id": 7},
        ],
    )

    result = runner.invoke(
        shotgrid_cli.app,
        ["bulk-playlists", "create", "--input", str(payload_file)],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary["entity"] == "Playlist"
    assert summary["requested"] == 2
    assert summary["succeeded"] == 2
    assert stub.created == [
        (
            "Playlist",
            [
                {"playlist_name": "Client Review", "project_id": 7},
                {"playlist_name": "Vendor Review", "project_id": 7},
            ],
        )
    ]


def test_bulk_versions_update_uses_payload_file(monkeypatch, tmp_path: Path) -> None:
    stub = StubShotgridClient()
    monkeypatch.setattr(shotgrid_cli, "ShotgridClient", lambda: stub)

    payload_file = _write_json(
        tmp_path,
        "versions.json",
        [
            {"id": 101, "description": "Updated notes"},
        ],
    )

    result = runner.invoke(
        shotgrid_cli.app,
        ["bulk-versions", "update", "--input", str(payload_file)],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary["entity"] == "Version"
    assert summary["requested"] == 1
    assert summary["succeeded"] == 1
    assert stub.updated == [
        ("Version", [{"id": 101, "description": "Updated notes"}])
    ]


def test_bulk_playlists_delete_accepts_ids(monkeypatch) -> None:
    stub = StubShotgridClient()
    monkeypatch.setattr(shotgrid_cli, "ShotgridClient", lambda: stub)

    result = runner.invoke(
        shotgrid_cli.app,
        ["bulk-playlists", "delete", "--id", "5", "--id", "9"],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary["entity"] == "Playlist"
    assert summary["ids"] == [5, 9]
    assert stub.deleted == [("Playlist", [5, 9])]


def test_bulk_versions_delete_accepts_input_file(monkeypatch, tmp_path: Path) -> None:
    stub = StubShotgridClient()
    monkeypatch.setattr(shotgrid_cli, "ShotgridClient", lambda: stub)

    ids_file = _write_json(tmp_path, "ids.json", [11, "12"])

    result = runner.invoke(
        shotgrid_cli.app,
        ["bulk-versions", "delete", "--input", str(ids_file)],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary["entity"] == "Version"
    assert summary["ids"] == [11, 12]
    assert stub.deleted == [("Version", [11, 12])]
