"""Tests for the ShotGrid version-zero CLI command."""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.onepiece.utils.errors import OnePieceValidationError

version_zero = importlib.import_module("apps.onepiece.shotgrid.version_zero")

runner = CliRunner()


class _MissingProjectShotGridClient:
    def get_project_id_by_name(self, project_name: str) -> None:  # noqa: D401 - stub
        return None


class _ShotGridClientFactory:
    @staticmethod
    def from_env() -> _MissingProjectShotGridClient:
        return _MissingProjectShotGridClient()


def test_version_zero_errors_when_project_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    csv_path = tmp_path / "shots.csv"
    csv_path.write_text("shot\nE01_S01_SH001\n")

    monkeypatch.setattr(version_zero, "ShotGridClient", _ShotGridClientFactory)

    result = runner.invoke(
        version_zero.app,
        [str(csv_path), "--project-name", "MissingProject"],
    )

    assert isinstance(result.exception, OnePieceValidationError)
    message = str(result.exception)
    assert "MissingProject" in message
    assert "Project" in message


def test_version_zero_sets_version_entity_relationship(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    csv_path = tmp_path / "shots.csv"
    csv_path.write_text("shot\nE01_S01_SH001\n")

    exr_root = tmp_path / "E01_S01_SH001"
    exr_dir = exr_root / "exr"
    exr_dir.mkdir(parents=True)

    class _StubFilepathHandler:
        def __init__(self) -> None:  # noqa: D401 - stub
            self.calls: list[tuple[str, str, str, str]] = []

        def get_shot_dir(
            self, project_name: str, episode: str, scene: str, shot: str
        ) -> Path:
            self.calls.append((project_name, episode, scene, shot))
            return exr_root

    class _StubShotGridClient:
        def __init__(self) -> None:
            self.version_data: object | None = None
            self.media_path: Path | None = None

        def get_project_id_by_name(self, project_name: str) -> int:
            return 55

        def get_shot(self, project_id: int, shot_name: str) -> dict[str, object]:
            return {
                "id": 777,
                "type": "Shot",
                "related_entity_type": "Shot",
            }

        def get_task(self, entity_id: int, task_name: object) -> dict[str, object]:
            return {"id": 123}

        def create_task(
            self, *, data: object, step: object
        ) -> None:  # noqa: D401 - stub
            return None

        def create_version_with_media(
            self, version_data: object, media_path: Path
        ) -> dict[str, object]:
            self.version_data = version_data
            self.media_path = media_path
            return {"id": 999}

    class _ProgressStub:
        def advance(self, *, description: str | None = None, step: float = 1.0) -> None:
            return None

        def succeed(self, message: str) -> None:
            return None

    stub_client = _StubShotGridClient()

    @contextmanager
    def _progress_factory(*args: object, **kwargs: object) -> Any:
        yield _ProgressStub()

    class _StubClientFactory:
        @staticmethod
        def from_env() -> _StubShotGridClient:
            return stub_client

    monkeypatch.setattr(version_zero, "FilepathHandler", _StubFilepathHandler)
    monkeypatch.setattr(version_zero, "ShotGridClient", _StubClientFactory)

    def _create_proxy(_: Path, proxy_path: Path, *, fps: int) -> None:
        proxy_path.write_bytes(b"mov")

    monkeypatch.setattr(version_zero, "create_1080p_proxy_from_exrs", _create_proxy)
    monkeypatch.setattr(version_zero, "progress_tracker", _progress_factory)

    result = runner.invoke(
        version_zero.app,
        [str(csv_path), "--project-name", "Demo"],
    )

    assert result.exit_code == 0
    assert stub_client.version_data is not None
    version_data = stub_client.version_data
    entity = version_data.extra.get("entity")  # type: ignore[attr-defined]
    assert entity == {"data": {"type": "Shot", "id": 777}}
    assert stub_client.media_path == exr_dir / "E01_S01_SH001_proxy.mov"
