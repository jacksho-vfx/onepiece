from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog

from .client import Playlist, ShotgridClient, Version

log = structlog.get_logger(__name__)

Recipient = Literal["client", "vendor"]


@dataclass(frozen=True)
class PlaylistPackageSummary:
    """Details about a packaged ShotGrid playlist."""

    package_path: Path
    manifest: dict[str, Any]


def _slugify(value: str) -> str:
    """Return a filesystem-friendly version of ``value``."""

    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned or "package"


def _ensure_package_dir(base_dir: Path) -> None:
    if base_dir.exists():
        # Avoid mixing existing deliveries with new runs.
        if any(base_dir.iterdir()):
            raise FileExistsError(f"Destination '{base_dir}' already contains files")
    base_dir.mkdir(parents=True, exist_ok=True)


def _build_package_directory(
    destination: Path, playlist: Playlist, recipient: Recipient
) -> Path:
    project_slug = _slugify(playlist["project"])
    playlist_slug = _slugify(playlist["playlist_name"])
    package_name = (
        f"{project_slug}_{playlist_slug}_{recipient}_playlist_{playlist['id']:04d}"
    )
    package_dir = destination / package_name
    _ensure_package_dir(package_dir)
    return package_dir


def _copy_media(
    media_dir: Path, version: Version, source: Path
) -> tuple[Path, dict[str, Any]]:
    if not source.exists():
        raise FileNotFoundError(f"Media source not found: {source}")

    base_name = _slugify(version["code"] or source.stem)
    suffix = source.suffix
    destination = media_dir / f"{base_name}{suffix}"
    counter = 1
    while destination.exists():
        destination = media_dir / f"{base_name}_{counter}{suffix}"
        counter += 1

    log.debug(
        "playlist_delivery.copy_media",
        version=version["id"],
        src=str(source),
        dst=str(destination),
    )
    shutil.copy2(str(source), str(destination))

    item = {
        "version_id": version["id"],
        "code": version["code"],
        "source": str(source),
        "packaged_path": str(destination),
        "shot": version.get("shot", ""),
        "description": version.get("description", ""),
    }
    return destination, item


def package_playlist_for_mediashuttle(
    sg_client: ShotgridClient,
    project_name: str,
    playlist_name: str,
    destination: Path,
    recipient: Recipient,
) -> PlaylistPackageSummary:
    """Package playlist media ready for MediaShuttle delivery."""

    log.info(
        "playlist_delivery.start",
        project=project_name,
        playlist=playlist_name,
        destination=str(destination),
        recipient=recipient,
    )

    playlist = sg_client.get_playlist(project_name, playlist_name)
    if playlist is None:
        raise ValueError(
            f"Playlist '{playlist_name}' not found in project '{project_name}'"
        )

    versions: list[Version] = []
    for version_id in playlist.get("version_ids", []):
        version = sg_client.get_version_by_id(int(version_id))
        if version is None:
            raise ValueError(
                f"Playlist '{playlist_name}' references unknown version id {version_id}"
            )
        versions.append(version)

    if not versions:
        raise ValueError(
            f"Playlist '{playlist_name}' in project '{project_name}' does not contain any versions"
        )

    package_dir = _build_package_directory(destination, playlist, recipient)
    media_dir = package_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    for version in versions:
        source = Path(version["path"])
        _, manifest_entry = _copy_media(media_dir, version, source)
        items.append(manifest_entry)

    manifest = {
        "project": playlist["project"],
        "playlist": playlist["playlist_name"],
        "playlist_id": playlist["id"],
        "recipient": recipient,
        "item_count": len(items),
        "items": items,
    }

    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log.info("playlist_delivery.complete", package=str(package_dir))

    return PlaylistPackageSummary(package_path=package_dir, manifest=manifest)
