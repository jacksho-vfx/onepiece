"""Tests for playlist packaging workflows."""

import json
from pathlib import Path
from typing import cast

import pytest

from libraries.integrations.shotgrid.client import ShotgridClient
from libraries.integrations.shotgrid.playlist_delivery import package_playlist_for_mediashuttle


@pytest.fixture()
def sg_client() -> ShotgridClient:
    return ShotgridClient()


def _create_version(
    sg_client: ShotgridClient, project: str, shot: str, path: Path
) -> int:
    version = sg_client.register_version(project, shot, path)
    return cast(int, version["id"])


def test_package_playlist_for_mediashuttle(
    tmp_path: Path, sg_client: ShotgridClient
) -> None:
    project = "OnePiece"
    media_root = Path(tmp_path) / "media"
    media_root.mkdir()

    version_ids: list[int] = []
    for index, shot in enumerate(["sh010", "sh020"], start=1):
        media_file = media_root / f"shot_{shot}.mov"
        media_file.write_text(f"media {index}")
        version_ids.append(
            _create_version(
                sg_client,
                project=project,
                shot=shot,
                path=media_file,
            )
        )

    sg_client.register_playlist(project, "Client Review", version_ids)

    destination = Path(tmp_path) / "packages"
    destination.mkdir()

    summary = package_playlist_for_mediashuttle(
        sg_client,
        project_name=project,
        playlist_name="Client Review",
        destination=destination,
        recipient="client",
    )

    package_dir = summary.package_path
    assert package_dir.exists()

    media_dir = package_dir / "media"
    assert sorted(p.name for p in media_dir.iterdir()) == [
        "shot_sh010.mov",
        "shot_sh020.mov",
    ]

    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["playlist"] == "Client Review"
    assert manifest["recipient"] == "client"
    assert manifest["item_count"] == 2
    packaged_sources = {item["source"] for item in manifest["items"]}
    assert packaged_sources == {
        str(media_root / "shot_sh010.mov"),
        str(media_root / "shot_sh020.mov"),
    }


def test_package_playlist_missing(tmp_path: Path, sg_client: ShotgridClient) -> None:
    destination = Path(tmp_path) / "packages"
    destination.mkdir()

    with pytest.raises(ValueError):
        package_playlist_for_mediashuttle(
            sg_client,
            project_name="OnePiece",
            playlist_name="Unknown",
            destination=destination,
            recipient="client",
        )
