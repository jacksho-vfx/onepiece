"""Manifest parsing utilities for the ingest workflow."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, cast

from .models import _format_shot_name


class DeliveryManifestError(ValueError):
    """Raised when delivery manifest payloads cannot be parsed."""


@dataclass(frozen=True)
class Delivery:
    """Structured metadata describing a delivery manifest entry."""

    show: str
    episode: str
    scene: str
    shot: str
    asset: str
    version: int
    source_path: Path
    delivery_path: Path
    checksum: str | None = None

    @property
    def shot_name(self) -> str:
        return _format_shot_name(self.episode, self.scene, self.shot)


def _normalise_manifest_entry(
    entry: Mapping[str, object],
    *,
    index: int,
    manifest_path: Path,
) -> Delivery:
    def _normalise_manifest_path(value: object) -> Path:
        """Return a :class:`Path` that treats ``\\`` as directory separators."""

        text = str(value).strip()
        normalised = text.replace("\\", "/")
        return Path(normalised)

    normalised: dict[str, object] = {
        str(key).lower(): value for key, value in entry.items()
    }

    def _require(key: str) -> object:
        lowered = key.lower()
        if lowered not in normalised:
            raise DeliveryManifestError(
                f"Manifest entry {index} in '{manifest_path}' is missing '{key}'"
            )
        return normalised[lowered]

    checksum_value = normalised.get("checksum")
    checksum = None if checksum_value in (None, "") else str(checksum_value)

    version_raw = _require("version")
    try:
        version = int(cast(str, version_raw))
    except (TypeError, ValueError) as exc:
        raise DeliveryManifestError(
            f"Manifest entry {index} in '{manifest_path}' has an invalid version: {version_raw!r}"
        ) from exc

    delivery_path_raw = _require("delivery_path")
    if not delivery_path_raw:
        raise DeliveryManifestError(
            f"Manifest entry {index} in '{manifest_path}' has an empty delivery_path"
        )

    source_path_raw = _require("source_path")
    if not source_path_raw:
        raise DeliveryManifestError(
            f"Manifest entry {index} in '{manifest_path}' has an empty source_path"
        )

    return Delivery(
        show=str(_require("show")),
        episode=str(_require("episode")),
        scene=str(_require("scene")),
        shot=str(_require("shot")),
        asset=str(_require("asset")),
        version=version,
        source_path=_normalise_manifest_path(source_path_raw),
        delivery_path=_normalise_manifest_path(delivery_path_raw),
        checksum=checksum,
    )


def _load_manifest_rows(manifest_path: Path) -> list[Mapping[str, object]]:
    suffix = manifest_path.suffix.lower()
    if suffix == ".csv":
        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [
                {key: value for key, value in row.items() if key is not None}
                for row in reader
                if any((value or "").strip() for value in row.values())
            ]

    if suffix == ".json":
        with manifest_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, Mapping):
            if "files" in payload:
                rows = payload["files"]
            elif "deliveries" in payload:
                rows = payload["deliveries"]
            else:
                raise DeliveryManifestError(
                    f"JSON manifest '{manifest_path}' must contain a 'files' or 'deliveries' array"
                )
        else:
            raise DeliveryManifestError(
                f"Unsupported JSON manifest payload in '{manifest_path}': {type(payload).__name__}"
            )

        if not isinstance(rows, list):
            raise DeliveryManifestError(
                f"JSON manifest '{manifest_path}' has an invalid entry collection"
            )

        entries: list[Mapping[str, object]] = []
        for index, item in enumerate(rows):
            if not isinstance(item, Mapping):
                raise DeliveryManifestError(
                    f"Manifest entry {index} in '{manifest_path}' is not an object"
                )
            entries.append(cast(Mapping[str, object], item))
        return entries

    raise DeliveryManifestError(
        f"Unsupported manifest format for '{manifest_path}'. Provide a CSV or JSON manifest."
    )


def load_delivery_manifest(manifest_path: Path) -> list[Delivery]:
    """Return :class:`Delivery` entries parsed from *manifest_path*."""

    if not manifest_path.exists() or not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    rows = _load_manifest_rows(manifest_path)
    deliveries: list[Delivery] = []
    for index, entry in enumerate(rows):
        deliveries.append(
            _normalise_manifest_entry(entry, index=index, manifest_path=manifest_path)
        )
    return deliveries


def _build_manifest_index(deliveries: Sequence[Delivery]) -> dict[str, Delivery]:
    index: dict[str, Delivery] = {}
    for delivery in deliveries:
        relative = delivery.delivery_path.as_posix()
        index.setdefault(relative, delivery)
        index.setdefault(delivery.delivery_path.name, delivery)
    return index


__all__ = [
    "Delivery",
    "DeliveryManifestError",
    "load_delivery_manifest",
    "_build_manifest_index",
]
