"""Tests covering the ingest CLI's ShotGrid failure handling."""

import json
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
    IngestReport,
    IngestedMedia,
    MediaInfo,
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


def test_ingest_cli_writes_json_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "incoming"
    folder.mkdir()

    valid = folder / "SHOW01_ep001_sc01_0001_comp.mov"
    valid.write_bytes(b"data")
    invalid = folder / "invalid.mov"
    invalid.write_bytes(b"data")

    report = IngestReport(
        processed=[
            IngestedMedia(
                path=valid,
                bucket="vendor_in",
                key=f"SHOW01/{valid.name}",
                media_info=MediaInfo(
                    show_code="SHOW01",
                    episode="ep001",
                    scene="sc01",
                    shot="0001",
                    descriptor="comp",
                    extension="mov",
                ),
            )
        ],
        invalid=[(invalid, "bad naming")],
        warnings=[
            "Dry run: would upload SHOW01_ep001_sc01_0001_comp.mov",
            "Dry run: would register ShotGrid Version ep001_sc01_0001_comp",
        ],
    )

    class _Factory:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._report = report

        def ingest_folder(self, *args: object, **kwargs: object) -> IngestReport:
            return self._report

    monkeypatch.setattr(ingest_module, "MediaIngestService", _Factory)

    destination = tmp_path / "analytics.json"

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
            "--dry-run",
            "--report-format",
            "json",
            "--report-path",
            str(destination),
        ],
    )

    assert result.exception is None
    payload = json.loads(destination.read_text())
    assert payload["processed"][0]["file"].endswith(valid.name)
    assert payload["invalid"][0]["file"].endswith(invalid.name)
    assert "warnings" in payload


def test_ingest_cli_streams_csv_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "incoming"
    folder.mkdir()

    valid = folder / "SHOW01_ep001_sc01_0001_comp.mov"
    valid.write_bytes(b"data")

    report = IngestReport(
        processed=[
            IngestedMedia(
                path=valid,
                bucket="vendor_in",
                key=f"SHOW01/{valid.name}",
                media_info=MediaInfo(
                    show_code="SHOW01",
                    episode="ep001",
                    scene="sc01",
                    shot="0001",
                    descriptor="comp",
                    extension="mov",
                ),
            )
        ],
        warnings=["Dry run: would upload"],
    )

    class _Factory:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._report = report

        def ingest_folder(self, *args: object, **kwargs: object) -> IngestReport:
            return self._report

    monkeypatch.setattr(ingest_module, "MediaIngestService", _Factory)

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
            "--dry-run",
            "--report-format",
            "csv",
        ],
    )

    assert result.exception is None
    assert "status,file,destination,details" in result.stdout
    assert "processed" in result.stdout
    assert "warning" in result.stdout
