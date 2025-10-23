from __future__ import annotations
import pytest

from libraries.automation.review import dailies
from libraries.automation.review.dailies import DailiesClip, _extract_duration


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
        self.last_paginated_call: tuple[str, list[dict[str, object]], str, int] | None = None

    def get_project(self, project_name: str) -> dict[str, object]:
        return {"id": 5001, "name": project_name}

    def _get_single(
        self, entity: str, filters: list[dict[str, object]], fields: str
    ) -> dict[str, object]:  # noqa: SLF001 - private API
        assert entity == "Playlist"
        assert any(filter_.get("code") == "Editorial" for filter_ in filters)
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

    def _get(self, *args, **kwargs):  # noqa: ANN001, D401, SLF001
        """The dailies module should rely on pagination."""

        raise AssertionError("_get should not be used when fetching versions")

    def _get_paginated(
        self,
        entity: str,
        filters: list[dict[str, object]],
        fields: str,
        page_size: int = 100,
    ) -> list[dict[str, object]]:  # noqa: SLF001 - private API
        assert entity == "Version"
        self.last_paginated_call = (entity, filters, fields, page_size)
        aggregated: list[dict[str, object]] = []
        for page in self._version_pages:
            aggregated.extend(page)
        return aggregated


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
    assert client.last_paginated_call == (
        "Version",
        [{"id[$in]": "101,102,103,104"}],
        dailies.VERSION_FIELDS,
        100,
    )
    assert all(isinstance(clip, DailiesClip) for clip in clips)
