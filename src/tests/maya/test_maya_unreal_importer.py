from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from apps.onepiece.utils.errors import OnePieceExternalServiceError
from libraries.creative.dcc.maya.unreal_importer import (
    UnrealImportError,
    UnrealImportSummary,
    UnrealPackageImporter,
)


unreal_import_cli = import_module("apps.onepiece.dcc.unreal_import")


class FakeAssetImportTask:
    def __init__(self) -> None:
        self.editor_properties: dict[str, object] = {}
        self.options: object | None = None

    def set_editor_property(self, name: str, value: object) -> None:
        self.editor_properties[name] = value


class FakeImportUI:
    def __init__(self) -> None:
        self.editor_properties: dict[str, object] = {}

    def set_editor_property(self, name: str, value: object) -> None:
        self.editor_properties[name] = value


class FakeAssetTools:
    def __init__(self) -> None:
        self.calls: list[list[FakeAssetImportTask]] = []

    def import_asset_tasks(self, tasks: list[FakeAssetImportTask]) -> None:
        self.calls.append(tasks)


class FakeAssetToolsHelpers:
    def __init__(self, tools: FakeAssetTools) -> None:
        self._tools = tools

    def get_asset_tools(self) -> FakeAssetTools:
        return self._tools


def _package_with_metadata(tmp_path: Path, status: str = "passed") -> Path:
    package = tmp_path / "package"
    renders = package / "renders"
    renders.mkdir(parents=True)
    mesh = renders / "hero.fbx"
    mesh.write_text("fbx data")

    metadata = {
        "dcc": "maya",
        "asset_name": "SK_Hero",
        "validations": {"maya_to_unreal": {"status": status}},
        "unreal": {
            "project_path": "/Game/Shows/OP/Heroes",
            "assets": [
                {
                    "source": "renders/hero.fbx",
                    "task_options": {"replace_existing": True},
                    "factory_options": {"import_materials": False},
                }
            ],
        },
    }

    package.mkdir(exist_ok=True)
    (package / "metadata.json").write_text(json.dumps(metadata))
    return package


def _fake_unreal(tooling: FakeAssetTools) -> SimpleNamespace:
    return SimpleNamespace(
        AssetImportTask=FakeAssetImportTask,
        AssetToolsHelpers=FakeAssetToolsHelpers(tooling),
        FbxImportUI=FakeImportUI,
    )


def test_unreal_importer_runs_tasks_for_validated_package(tmp_path: Path) -> None:
    package = _package_with_metadata(tmp_path)
    tooling = FakeAssetTools()
    unreal = _fake_unreal(tooling)

    importer = UnrealPackageImporter(unreal_module=unreal)

    summaries = importer.import_package(
        package,
        project="OP",
        asset_name="Hero",
    )

    assert len(tooling.calls) == 1
    tasks = tooling.calls[0]
    assert len(tasks) == 1
    task = tasks[0]

    mesh_path = package / "renders" / "hero.fbx"
    assert task.editor_properties["filename"] == str(mesh_path)
    assert task.editor_properties["destination_path"] == "/Game/Shows/OP/Heroes"
    assert task.editor_properties["destination_name"] == "SK_Hero"
    assert task.editor_properties["replace_existing"] is True
    assert task.editor_properties["automated"] is True
    assert task.editor_properties["save"] is True

    assert isinstance(task.options, FakeImportUI)
    assert task.options.editor_properties["import_materials"] is False

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.source == mesh_path
    assert summary.destination_name == "SK_Hero"


def test_unreal_importer_supports_dry_run(tmp_path: Path) -> None:
    package = _package_with_metadata(tmp_path)
    importer = UnrealPackageImporter()

    summaries = importer.import_package(
        package,
        project="OP",
        asset_name="Hero",
        dry_run=True,
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.destination_path == "/Game/Shows/OP/Heroes"


def test_unreal_importer_rejects_failed_validation(tmp_path: Path) -> None:
    package = _package_with_metadata(tmp_path, status="failed")
    importer = UnrealPackageImporter()

    with pytest.raises(UnrealImportError):
        importer.import_package(package, project="OP", asset_name="Hero")


def test_unreal_import_cli_outputs_dry_run_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = _package_with_metadata(tmp_path)
    runner = CliRunner()
    called: dict[str, object] = {}

    summary = UnrealImportSummary(
        source=package / "renders" / "hero.fbx",
        destination_path="/Game/Shows/OP/Heroes",
        destination_name="SK_Hero",
        task_settings={"automated": True, "replace_existing": True, "save": True},
        factory_class=None,
        factory_settings={"import_materials": False},
    )

    class DummyImporter:
        def import_package(
            self,
            package_dir: Path,
            *,
            project: str,
            asset_name: str,
            dry_run: bool,
        ) -> list[UnrealImportSummary]:
            called["package"] = package_dir
            called["project"] = project
            called["asset"] = asset_name
            called["dry_run"] = dry_run
            return [summary]

    monkeypatch.setattr(
        unreal_import_cli,
        "UnrealPackageImporter",
        lambda: DummyImporter(),
    )

    result = runner.invoke(
        unreal_import_cli.app,
        [
            "--package",
            str(package),
            "--project",
            "OP",
            "--asset",
            "Hero",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called["package"] == package
    assert called["project"] == "OP"
    assert called["asset"] == "Hero"
    assert called["dry_run"] is True
    assert '"destination_path": "/Game/Shows/OP/Heroes"' in result.output


def test_unreal_import_cli_surfaces_import_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = _package_with_metadata(tmp_path)
    runner = CliRunner()

    class FailingImporter:
        def import_package(self, *args: object, **kwargs: object) -> None:
            raise UnrealImportError("boom")

    monkeypatch.setattr(
        unreal_import_cli,
        "UnrealPackageImporter",
        lambda: FailingImporter(),
    )

    result = runner.invoke(
        unreal_import_cli.app,
        [
            "--package",
            str(package),
            "--project",
            "OP",
            "--asset",
            "Hero",
        ],
    )

    assert isinstance(result.exception, OnePieceExternalServiceError)
