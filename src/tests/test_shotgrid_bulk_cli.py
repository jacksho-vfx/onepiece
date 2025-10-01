"""Tests for the Shotgrid bulk CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from importlib import import_module
import yaml
from libraries.shotgrid.client import HierarchyTemplate, ShotgridClient

shotgrid_cli = import_module("apps.onepiece.shotgrid.package_playlist")
templates_cli = import_module("apps.onepiece.shotgrid.templates")


class StubShotgridClient:
    """Record calls made by the bulk CLI for verification."""

    def __init__(self) -> None:
        self.created: list[tuple[str, list[dict[str, object]]]] = []
        self.updated: list[tuple[str, list[dict[str, object]]]] = []
        self.deleted: list[tuple[str, list[int]]] = []

    def bulk_create_entities(
        self, entity_type: str, payloads: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        payload_list = list(payloads)
        self.created.append((entity_type, payload_list))
        return [
            {"id": index + 1, **payload} for index, payload in enumerate(payload_list)
        ]

    def bulk_update_entities(
        self, entity_type: str, payloads: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        payload_list = list(payloads)
        self.updated.append((entity_type, payload_list))
        return payload_list

    def bulk_delete_entities(self, entity_type: str, entity_ids: list[int]) -> None:
        ids = [int(entity_id) for entity_id in entity_ids]
        self.deleted.append((entity_type, ids))


class TemplateStubShotgridClient(ShotgridClient):  # type: ignore[misc]
    """Extension of the in-memory client that records template interactions."""

    def __init__(self) -> None:
        super().__init__(sleep=lambda _: None)
        self.deserialized: list[HierarchyTemplate] = []
        self.saved_paths: list[Path] = []
        self.loaded_paths: list[Path] = []
        self.applied: list[tuple[str, HierarchyTemplate, dict[str, Any]]] = []

    def deserialize_hierarchy_template(self, data: dict[str, Any]) -> HierarchyTemplate:
        template = super().deserialize_hierarchy_template(data)
        self.deserialized.append(template)
        return template

    def save_hierarchy_template(self, template: HierarchyTemplate, path: Path) -> None:
        self.saved_paths.append(path)
        super().save_hierarchy_template(template, path)

    def load_hierarchy_template(self, path: Path) -> HierarchyTemplate:
        template = super().load_hierarchy_template(path)
        self.loaded_paths.append(path)
        return template

    def apply_hierarchy_template(
        self,
        project_name: str,
        template: HierarchyTemplate,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        result = super().apply_hierarchy_template(
            project_name, template, context=context
        )
        self.applied.append((project_name, template, dict(context or {})))
        return result


runner = CliRunner()


def _write_json(tmp_path: Path, name: str, data: object) -> Path:
    file_path = tmp_path / name
    file_path.write_text(json.dumps(data))
    return file_path


def _write_yaml(tmp_path: Path, name: str, data: object) -> Path:
    file_path = tmp_path / name
    file_path.write_text(yaml.safe_dump(data))
    return file_path


def _parse_summary(output: str) -> Any:
    start = output.find("{")
    assert start != -1, output
    return json.loads(output[start:])


def _template_payload() -> dict[str, Any]:
    return {
        "name": "episodic",
        "roots": [
            {
                "entity_type": "Episode",
                "attributes": {"code": "ep001"},
                "children": [
                    {
                        "entity_type": "Scene",
                        "attributes": {"code": "sc001"},
                    }
                ],
            }
        ],
    }


def test_bulk_playlists_create_uses_payload_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    assert summary == {
        "entity": "Playlist",
        "failed": 0,
        "ids": [1, 2],
        "operation": "create",
        "requested": 2,
        "succeeded": 2,
    }
    assert stub.created == [
        (
            "Playlist",
            [
                {"playlist_name": "Client Review", "project_id": 7},
                {"playlist_name": "Vendor Review", "project_id": 7},
            ],
        )
    ]


def test_bulk_playlists_create_accepts_yaml_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stub = StubShotgridClient()
    monkeypatch.setattr(shotgrid_cli, "ShotgridClient", lambda: stub)

    payload_file = _write_yaml(
        tmp_path,
        "playlists.yaml",
        [
            {"playlist_name": "Review A", "project_id": 3},
            {"playlist_name": "Review B", "project_id": 3},
        ],
    )

    result = runner.invoke(
        shotgrid_cli.app,
        ["bulk-playlists", "create", "--input", str(payload_file)],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary["requested"] == 2
    assert stub.created == [
        (
            "Playlist",
            [
                {"playlist_name": "Review A", "project_id": 3},
                {"playlist_name": "Review B", "project_id": 3},
            ],
        )
    ]


def test_bulk_versions_update_uses_payload_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    assert summary == {
        "entity": "Version",
        "failed": 0,
        "ids": [101],
        "operation": "update",
        "requested": 1,
        "succeeded": 1,
    }
    assert stub.updated == [("Version", [{"id": 101, "description": "Updated notes"}])]


def test_bulk_playlists_delete_accepts_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubShotgridClient()
    monkeypatch.setattr(shotgrid_cli, "ShotgridClient", lambda: stub)

    result = runner.invoke(
        shotgrid_cli.app,
        ["bulk-playlists", "delete", "--id", "5", "--id", "9"],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary == {
        "entity": "Playlist",
        "failed": 0,
        "ids": [5, 9],
        "operation": "delete",
        "requested": 2,
        "succeeded": 2,
    }
    assert stub.deleted == [("Playlist", [5, 9])]


def test_bulk_versions_delete_accepts_input_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stub = StubShotgridClient()
    monkeypatch.setattr(shotgrid_cli, "ShotgridClient", lambda: stub)

    ids_file = _write_json(tmp_path, "ids.json", [11, "12"])

    result = runner.invoke(
        shotgrid_cli.app,
        ["bulk-versions", "delete", "--input", str(ids_file)],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary == {
        "entity": "Version",
        "failed": 0,
        "ids": [11, 12],
        "operation": "delete",
        "requested": 2,
        "succeeded": 2,
    }
    assert stub.deleted == [("Version", [11, 12])]


def test_bulk_versions_delete_accepts_yaml_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stub = StubShotgridClient()
    monkeypatch.setattr(shotgrid_cli, "ShotgridClient", lambda: stub)

    ids_file = _write_yaml(tmp_path, "ids.yaml", [11, 12])

    result = runner.invoke(
        shotgrid_cli.app,
        ["bulk-versions", "delete", "--input", str(ids_file)],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary == {
        "entity": "Version",
        "failed": 0,
        "ids": [11, 12],
        "operation": "delete",
        "requested": 2,
        "succeeded": 2,
    }
    assert stub.deleted == [("Version", [11, 12])]


def test_save_template_command_writes_normalized_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stub = TemplateStubShotgridClient()
    monkeypatch.setattr(templates_cli, "ShotgridClient", lambda: stub)

    input_path = _write_yaml(tmp_path, "template.yaml", _template_payload())
    output_path = tmp_path / "normalized.json"

    result = runner.invoke(
        templates_cli.app,
        ["save-template", "--input", str(input_path), "--output", str(output_path)],
    )

    assert result.exit_code == 0
    assert output_path.exists()

    summary = _parse_summary(result.stdout)
    assert summary == {"output": str(output_path), "template": "episodic"}

    assert stub.saved_paths == [output_path]
    assert stub.deserialized and stub.deserialized[0].name == "episodic"

    saved_payload = json.loads(output_path.read_text())
    assert saved_payload["name"] == "episodic"
    assert saved_payload["roots"][0]["entity_type"] == "Episode"


def test_load_template_command_applies_template_with_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stub = TemplateStubShotgridClient()
    monkeypatch.setattr(templates_cli, "ShotgridClient", lambda: stub)

    template_path = _write_json(tmp_path, "template.json", _template_payload())
    context_path = _write_yaml(tmp_path, "context.yaml", {"department": "lighting"})

    result = runner.invoke(
        templates_cli.app,
        [
            "load-template",
            "--input",
            str(template_path),
            "--project",
            "Cool Project",
            "--context",
            str(context_path),
        ],
    )

    assert result.exit_code == 0

    summary = _parse_summary(result.stdout)
    assert summary == {
        "created": {"Episode": 1, "Scene": 1},
        "project": "Cool Project",
        "template": "episodic",
    }

    assert stub.loaded_paths == [template_path]
    assert stub.applied and stub.applied[0][0] == "Cool Project"
    assert stub.applied[0][2] == {"department": "lighting"}
