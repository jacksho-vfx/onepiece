"""Tests covering the ingest CLI's ShotGrid failure handling."""

from pathlib import Path

import pytest
from click.testing import Result
from typer.testing import CliRunner

from apps.onepiece.app import app
import importlib

from apps.onepiece.utils.errors import (
    ExitCode,
    OnePieceConfigError,
    OnePieceExternalServiceError,
    OnePieceValidationError,
)
from libraries.ingest.service import (
    ShotgridAuthenticationError,
    ShotgridConnectivityError,
    ShotgridSchemaError,
)

ingest_module = importlib.import_module("apps.onepiece.aws.ingest")
runner = CliRunner()


class _StubService:
    def __init__(self, *, error: Exception) -> None:
        self._error = error

    def ingest_folder(self, *_: object, **__: object) -> None:
        raise self._error


def _invoke_with_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> Result:
    class _Factory:
        def __init__(
            self, *args: object, **kwargs: object
        ) -> None:  # noqa: D401 - test stub
            self._service = _StubService(error=error)

        def ingest_folder(self, *args: object, **kwargs: object) -> None:
            return self._service.ingest_folder(*args, **kwargs)

    monkeypatch.setattr(ingest_module, "MediaIngestService", _Factory)

    folder = tmp_path / "incoming"
    folder.mkdir()
    media = folder / "dummy.mov"
    media.write_text("")

    return runner.invoke(
        app,
        [
            "aws",
            "ingest",
            str(folder),
            "--project",
            "CoolShow",
            "--show-code",
            "SHOW01",
            "--dry-run",
        ],
    )


def test_ingest_cli_warns_on_empty_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "incoming"
    folder.mkdir()

    def _unexpected_service(
        *args: object, **kwargs: object
    ) -> None:  # pragma: no cover
        raise AssertionError(
            "MediaIngestService should not be constructed for empty folders"
        )

    monkeypatch.setattr(ingest_module, "MediaIngestService", _unexpected_service)

    result = runner.invoke(
        app,
        [
            "aws",
            "ingest",
            str(folder),
            "--project",
            "CoolShow",
            "--show-code",
            "SHOW01",
        ],
    )

    assert isinstance(result.exception, OnePieceValidationError)
    message = str(result.exception)
    assert "No media files" in message
    assert "--dry-run" in message


def test_ingest_cli_maps_authentication_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _invoke_with_error(
        monkeypatch,
        tmp_path,
        ShotgridAuthenticationError(
            "ShotGrid rejected the provided credentials while registering 'ep001'."
        ),
    )

    assert isinstance(result.exception, OnePieceConfigError)
    assert result.exception.exit_code == ExitCode.CONFIG
    message = str(result.exception)
    assert "credentials" in message
    assert "retry" in message.lower()


def test_ingest_cli_maps_schema_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _invoke_with_error(
        monkeypatch,
        tmp_path,
        ShotgridSchemaError(
            "ShotGrid rejected the version payload for 'ep001'. Confirm the shot."
        ),
    )

    assert isinstance(result.exception, OnePieceValidationError)
    assert result.exception.exit_code == ExitCode.VALIDATION
    message = str(result.exception)
    assert "ShotGrid rejected" in message
    assert "retry" in message.lower()


def test_ingest_cli_maps_connectivity_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _invoke_with_error(
        monkeypatch,
        tmp_path,
        ShotgridConnectivityError(
            "ShotGrid did not respond while registering 'ep001'."
        ),
    )

    assert isinstance(result.exception, OnePieceExternalServiceError)
    assert result.exception.exit_code == ExitCode.EXTERNAL
    message = str(result.exception)
    assert "ShotGrid did not respond" in message
    assert "retry" in message.lower()
