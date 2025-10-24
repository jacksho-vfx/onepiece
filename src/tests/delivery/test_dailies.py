from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import pytest
from typer.testing import CliRunner

from apps.onepiece import app as onepiece_app
from libraries.automation.review import dailies
from libraries.automation.review.dailies import DailiesClip, _extract_duration


runner = CliRunner()


def _make_version_record(
    identifier: int,
    *,
    code: str,
    shot: str,
    user: str,
    frame_range: str,
) -> dict[str, object]:
    return {
        "id": identifier,
        "attributes": {
            "code": code,
            "version_number": code,
            "sg_path_to_movie": f"/path/to/{code}.mov",
            "frame_range": frame_range,
            "sg_uploaded_movie_frame_count": 120,
            "sg_uploaded_movie_frame_rate": 24,
        },
        "relationships": {
            "entity": {"data": {"name": shot}},
            "user": {"data": {"name": user}},
        },
    }


class _PaginatedShotGridClient:
    """Stub ShotGrid client that exposes paginated version records."""

    def __init__(self) -> None:
        self._version_pages: list[list[dict[str, object]]] = [
            [
                _make_version_record(
                    101,
                    code="shot_001_v001",
                    shot="shot_001",
                    user="artist_a",
                    frame_range="1001-1050",
                ),
                _make_version_record(
                    102,
                    code="shot_002_v001",
                    shot="shot_002",
                    user="artist_b",
                    frame_range="1051-1100",
                ),
            ],
            [
                _make_version_record(
                    103,
                    code="shot_003_v001",
                    shot="shot_003",
                    user="artist_c",
                    frame_range="1101-1150",
                ),
                _make_version_record(
                    104,
                    code="shot_004_v001",
                    shot="shot_004",
                    user="artist_d",
                    frame_range="1151-1200",
                ),
            ],
        ]
        self.last_playlist_call: tuple[list[dict[str, object]], str] | None = None
        self.last_versions_call: (
            tuple[list[dict[str, object]], str, int | None] | None
        ) = None

    def get_project(self, project_name: str) -> dict[str, object]:
        return {"id": 5001, "name": project_name}

    def get_playlist_record(
        self,
        filters: list[dict[str, object]],
        fields: Sequence[str] | str = ("id", "name", "code", "versions"),
    ) -> dict[str, object]:
        assert any(filter_.get("code") == "Editorial" for filter_ in filters)

        if isinstance(fields, str):
            field_param = fields
        else:
            field_param = ",".join(str(field).strip() for field in fields if field)

        self.last_playlist_call = (filters, field_param)

        return {
            "relationships": {
                "versions": {
                    "data": [
                        {"id": str(record["id"])}
                        for page in self._version_pages
                        for record in page
                    ]
                }
            }
        }

    def list_versions_raw(
        self,
        filters: list[dict[str, object]],
        fields: str,
        *,
        page_size: int | None = 100,
    ) -> list[dict[str, object]]:
        assert page_size == 100
        self.last_versions_call = (filters, fields, page_size)
        aggregated: list[dict[str, object]] = []
        for page in self._version_pages:
            aggregated.extend(page)
        return aggregated

    def _get(
        self, *args: Any, **kwargs: Any
    ) -> AssertionError:  # noqa: ANN001, D401, SLF001
        """The dailies module should route through list_versions_raw."""

        raise AssertionError("_get should not be used when fetching versions")


def test_extract_duration_handles_zero_frame_count() -> None:
    attributes: dict[str, object] = {
        "sg_uploaded_movie_frame_count": 0,
        "sg_uploaded_movie_frame_rate": 24,
    }

    assert _extract_duration(attributes) == pytest.approx(0.0)


def test_fetch_playlist_versions_aggregates_paginated_results() -> None:
    client = _PaginatedShotGridClient()

    clips = dailies.fetch_playlist_versions(client, "My Show", "Editorial")

    assert isinstance(clips, list)
    assert [clip.version for clip in clips] == [
        "shot_001_v001",
        "shot_002_v001",
        "shot_003_v001",
        "shot_004_v001",
    ]
    assert client.last_playlist_call == (
        [{"project": 5001}, {"code": "Editorial"}],
        "id,name,code,versions",
    )
    assert client.last_versions_call == (
        [{"id[$in]": "101,102,103,104"}],
        dailies.VERSION_FIELDS,
        100,
    )
    assert all(isinstance(clip, DailiesClip) for clip in clips)


def test_dailies_cli_creates_missing_output_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "nested" / "dailies.mov"
    assert not output.parent.exists()

    clips = [
        DailiesClip(
            shot="shot_001",
            version="shot_001_v001",
            source_path=str(tmp_path / "shot_001_v001.mov"),
            frame_range="1001-1050",
            user="artist_a",
            duration_seconds=5.0,
        )
    ]

    clips[0].source_path and Path(clips[0].source_path).write_bytes(b"frames")

    monkeypatch.setattr(dailies, "get_shotgrid_client", lambda: object())
    monkeypatch.setattr(
        dailies, "fetch_playlist_versions", lambda client, project, playlist: clips
    )

    def _unused_fetch_today(*args: Any, **kwargs: Any) -> None:  # pragma: no cover
        pytest.fail("fetch_today_approved_versions should not be called")

    monkeypatch.setattr(dailies, "fetch_today_approved_versions", _unused_fetch_today)

    def _fake_create_concat_file(sources: Sequence[str], directory: Path) -> Path:
        concat = directory / "concat.txt"
        concat.write_text("\n".join(sources), encoding="utf-8")
        return concat

    monkeypatch.setattr(dailies, "create_concat_file", _fake_create_concat_file)

    ffmpeg_calls: list[Path] = []

    def _fake_run_ffmpeg_concat(
        concat_path: Path,
        output_path: Path,
        *,
        codec: str,
        burnins: Sequence[Any] | None,
    ) -> None:
        ffmpeg_calls.append(output_path)
        assert output_path.parent.exists()
        output_path.write_bytes(b"rendered")

    monkeypatch.setattr(dailies, "run_ffmpeg_concat", _fake_run_ffmpeg_concat)

    def _fake_write_manifest(
        output_path: Path, clips_arg: Sequence[Any], *, codec: str
    ) -> Path:
        manifest_path = output_path.with_name(f"{output_path.name}.manifest.json")
        manifest_path.write_text("{}", encoding="utf-8")
        return manifest_path

    monkeypatch.setattr(dailies, "write_manifest", _fake_write_manifest)

    result = runner.invoke(
        onepiece_app.app,
        [
            "review",
            "dailies",
            "--project",
            "My Show",
            "--playlist",
            "Editorial",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert output.exists()
    assert ffmpeg_calls == [output]
    manifest_path = output.with_name(f"{output.name}.manifest.json")
    assert manifest_path.exists()
