"""Asset type detection and capability helpers for ingest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ASSET_TYPE_UNKNOWN = "unknown"
ASSET_TYPE_MODEL = "3d_model"
ASSET_TYPE_TEXTURE = "texture"
ASSET_TYPE_IMAGE = "image"
ASSET_TYPE_CACHE = "cache"
ASSET_TYPE_VIDEO = "video"
ASSET_TYPE_AUDIO = "audio"


_TYPE_MAP: dict[str, tuple[str, ...]] = {
    ".fbx": (ASSET_TYPE_MODEL,),
    ".obj": (ASSET_TYPE_MODEL,),
    ".gltf": (ASSET_TYPE_MODEL,),
    ".glb": (ASSET_TYPE_MODEL,),
    ".abc": (ASSET_TYPE_MODEL, ASSET_TYPE_CACHE),
    ".usd": (ASSET_TYPE_MODEL, ASSET_TYPE_CACHE),
    ".usda": (ASSET_TYPE_MODEL, ASSET_TYPE_CACHE),
    ".usdc": (ASSET_TYPE_MODEL, ASSET_TYPE_CACHE),
    ".blend": (ASSET_TYPE_MODEL,),
    ".ma": (ASSET_TYPE_MODEL,),
    ".mb": (ASSET_TYPE_MODEL,),
    ".exr": (ASSET_TYPE_TEXTURE, ASSET_TYPE_IMAGE),
    ".tif": (ASSET_TYPE_TEXTURE, ASSET_TYPE_IMAGE),
    ".tiff": (ASSET_TYPE_TEXTURE, ASSET_TYPE_IMAGE),
    ".png": (ASSET_TYPE_TEXTURE, ASSET_TYPE_IMAGE),
    ".jpg": (ASSET_TYPE_TEXTURE, ASSET_TYPE_IMAGE),
    ".jpeg": (ASSET_TYPE_TEXTURE, ASSET_TYPE_IMAGE),
    ".tx": (ASSET_TYPE_TEXTURE, ASSET_TYPE_IMAGE),
    ".vdb": (ASSET_TYPE_CACHE,),
    ".bgeo": (ASSET_TYPE_CACHE,),
    ".bgeo.sc": (ASSET_TYPE_CACHE,),
    ".mov": (ASSET_TYPE_VIDEO,),
    ".mp4": (ASSET_TYPE_VIDEO,),
    ".wav": (ASSET_TYPE_AUDIO,),
}

_MULTI_SUFFIXES = {".bgeo.sc"}


@dataclass(frozen=True)
class AssetCapabilities:
    can_optimize: bool
    can_validate: bool
    can_convert: bool


_CAPABILITIES: dict[str, AssetCapabilities] = {
    ASSET_TYPE_MODEL: AssetCapabilities(True, True, True),
    ASSET_TYPE_TEXTURE: AssetCapabilities(True, True, True),
    ASSET_TYPE_IMAGE: AssetCapabilities(True, True, True),
    ASSET_TYPE_CACHE: AssetCapabilities(True, True, False),
    ASSET_TYPE_VIDEO: AssetCapabilities(False, False, False),
    ASSET_TYPE_AUDIO: AssetCapabilities(False, False, False),
    ASSET_TYPE_UNKNOWN: AssetCapabilities(False, False, False),
}


def normalize_extension(path: Path) -> str:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if len(suffixes) >= 2:
        combined = "".join(suffixes[-2:])
        if combined in _MULTI_SUFFIXES:
            return combined
    return path.suffix.lower()


def detect_asset_types(extension: str) -> tuple[str, ...]:
    if not extension:
        return (ASSET_TYPE_UNKNOWN,)
    return _TYPE_MAP.get(extension.lower(), (ASSET_TYPE_UNKNOWN,))


def primary_asset_type(extension: str) -> str:
    types = detect_asset_types(extension)
    return types[0] if types else ASSET_TYPE_UNKNOWN


def collect_asset_types(extensions: Iterable[str]) -> set[str]:
    detected: set[str] = set()
    for ext in extensions:
        detected.update(detect_asset_types(ext))
    if not detected:
        detected.add(ASSET_TYPE_UNKNOWN)
    return detected


def build_capability_map(asset_types: Iterable[str]) -> dict[str, dict[str, bool]]:
    capabilities: dict[str, dict[str, bool]] = {}
    for asset_type in sorted(set(asset_types)):
        info = _CAPABILITIES.get(asset_type, _CAPABILITIES[ASSET_TYPE_UNKNOWN])
        capabilities[asset_type] = {
            "can_optimize": info.can_optimize,
            "can_validate": info.can_validate,
            "can_convert": info.can_convert,
        }
    return capabilities
