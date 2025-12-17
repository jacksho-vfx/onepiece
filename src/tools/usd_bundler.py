from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence

_ASSET_PATTERN = re.compile(r"@(?P<path>[^@]+)@")
_SUBLAYER_PATTERN = re.compile(r"subLayers\s*=\s*\[([^\]]*)\]", re.DOTALL)
_VARIANT_SET_PATTERN = re.compile(
    r'variantSet\s+"(?P<name>[^"]+)"\s*=\s*{', re.MULTILINE
)
_VARIANT_SELECTION_PATTERN = re.compile(
    r"variants\s*=\s*{(?P<body>[^}]*)}", re.MULTILINE | re.DOTALL
)
_STRING_SELECTION_PATTERN = re.compile(
    r'string\s+(?P<name>[A-Za-z0-9_]+)\s*=\s*"(?P<value>[^"]+)"'
)
_USD_EXTENSIONS = {".usd", ".usda", ".usdc", ".usdz"}
_MANIFEST_NAME = "bundle_manifest.json"


@dataclass(frozen=True)
class BundleArtifact:
    kind: Literal["layer", "texture"]
    source: Path
    bundled_path: Path
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "source": str(self.source),
            "bundled_path": str(self.bundled_path),
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> "BundleArtifact":
        return cls(
            kind=data.get("kind", "layer"),  # type: ignore[arg-type]
            source=Path(data.get("source", "")),
            bundled_path=Path(data.get("bundled_path", "")),
            sha256=data.get("sha256", ""),
        )


@dataclass(frozen=True)
class BundleManifest:
    root_layer: Path
    version_hash: str
    artifacts: tuple[BundleArtifact, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "root_layer": str(self.root_layer),
            "version_hash": self.version_hash,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "BundleManifest":
        artifacts = tuple(
            BundleArtifact.from_dict(entry)
            for entry in data.get("artifacts", [])  # type: ignore[arg-type, attr-defined]
        )
        root_layer = Path(str(data.get("root_layer", "")))
        version_hash = str(data.get("version_hash", ""))
        return cls(
            root_layer=root_layer, version_hash=version_hash, artifacts=artifacts
        )

    @classmethod
    def from_path(cls, path: Path) -> "BundleManifest":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(payload)


class BundleError(RuntimeError):
    """Raised when a bundle cannot be produced."""


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_usd_file(path: Path) -> bool:
    return path.suffix.lower() in _USD_EXTENSIONS


def _find_matching_brace(text: str, open_index: int) -> int:
    depth = 0
    for idx in range(open_index, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                return idx
    raise ValueError("Unbalanced braces in USD content")


def _extract_variant_option(body: str, choice: str) -> str:
    search_offset = 0
    option_pattern = re.compile(r'"(?P<name>[^"]+)"\s*{')
    while True:
        match = option_pattern.search(body, search_offset)
        if not match:
            return ""
        option_name = match.group("name")
        open_index = body.find("{", match.end() - 1)
        close_index = _find_matching_brace(body, open_index)
        if option_name == choice:
            return body[match.start() : close_index + 1]
        search_offset = close_index + 1


def _prune_variant_sets(content: str, selections: Mapping[str, str]) -> str:
    cursor = 0
    while True:
        match = _VARIANT_SET_PATTERN.search(content, cursor)
        if not match:
            break
        set_name = match.group("name")
        open_index = content.find("{", match.end() - 1)
        close_index = _find_matching_brace(content, open_index)

        choice = selections.get(set_name)
        if choice:
            body = content[open_index + 1 : close_index]
            selected = _extract_variant_option(body, choice)
            if selected:
                replacement = "{" + selected + "}"
                content = (
                    content[:open_index] + replacement + content[close_index + 1 :]
                )
                cursor = open_index + len(replacement)
                continue
        cursor = close_index + 1
    return content


def _apply_variant_metadata(content: str, selections: Mapping[str, str]) -> str:
    def _replace_body(match: re.Match[str]) -> str:
        body = match.group("body")
        updated = body
        for name, choice in selections.items():
            selection_pattern = re.compile(rf'string\s+{re.escape(name)}\s*=\s*"[^"]*"')
            if selection_pattern.search(updated):
                updated = selection_pattern.sub(f'string {name} = "{choice}"', updated)
            else:
                updated = updated.rstrip() + f'\n    string {name} = "{choice}"\n'
        return f"variants = {{{updated}}}"

    return _VARIANT_SELECTION_PATTERN.sub(_replace_body, content)


def _prune_variants(
    content: str, variant_overrides: Mapping[str, str]
) -> tuple[str, dict[str, str]]:
    selections = dict(variant_overrides)
    selection_blocks = _VARIANT_SELECTION_PATTERN.findall(content)
    for block in selection_blocks:
        for match in _STRING_SELECTION_PATTERN.finditer(block):
            name = match.group("name")
            value = match.group("value")
            selections.setdefault(name, value)

    pruned = _prune_variant_sets(content, selections)
    pruned = _apply_variant_metadata(pruned, selections)
    return pruned, selections


def _extract_asset_paths(content: str, *, base_dir: Path) -> set[Path]:
    assets: set[Path] = set()
    for match in _ASSET_PATTERN.finditer(content):
        raw_path = match.group("path").strip()
        candidate = Path(raw_path)
        resolved = candidate if candidate.is_absolute() else (base_dir / candidate)
        assets.add(resolved.resolve())
    return assets


def _rewrite_asset_references(
    content: str,
    *,
    source_layer: Path,
    destination_layer: Path,
    destination_map: Mapping[Path, Path],
) -> str:
    base_dir = source_layer.parent
    target_dir = destination_layer.parent

    def _replace(match: re.Match[str]) -> str:
        raw_path = match.group("path").strip()
        original = Path(raw_path)
        resolved = (
            original if original.is_absolute() else (base_dir / original).resolve()
        )
        bundled_target = destination_map.get(resolved)
        if not bundled_target:
            return match.group(0)
        relative = os.path.relpath(bundled_target, target_dir)
        normalized = relative.replace(os.sep, "/")
        return f"@{normalized}@"

    return _ASSET_PATTERN.sub(_replace, content)


def _resolve_sublayers(content: str, *, base_dir: Path) -> Iterable[Path]:
    for match in _SUBLAYER_PATTERN.finditer(content):
        layer_list = match.group(1)
        for asset_match in _ASSET_PATTERN.finditer(layer_list):
            candidate = Path(asset_match.group("path"))
            resolved = candidate if candidate.is_absolute() else (base_dir / candidate)
            yield resolved.resolve()


def _collect_layers(
    layer: Path,
    *,
    variant_overrides: Mapping[str, str],
    seen: set[Path],
    layer_content: dict[Path, str],
    textures: set[Path],
) -> None:
    resolved = layer.resolve()
    if resolved in seen:
        return
    if not resolved.exists():
        raise BundleError(f"USD layer '{layer}' does not exist")

    raw_content = resolved.read_text(encoding="utf-8")
    pruned, _ = _prune_variants(raw_content, variant_overrides)
    layer_content[resolved] = pruned
    seen.add(resolved)

    for sublayer in _resolve_sublayers(pruned, base_dir=resolved.parent):
        _collect_layers(
            sublayer,
            variant_overrides=variant_overrides,
            seen=seen,
            layer_content=layer_content,
            textures=textures,
        )

    for asset in _extract_asset_paths(pruned, base_dir=resolved.parent):
        if _is_usd_file(asset):
            _collect_layers(
                asset,
                variant_overrides=variant_overrides,
                seen=seen,
                layer_content=layer_content,
                textures=textures,
            )
        else:
            textures.add(asset)


def _build_destination_map(
    layers: Sequence[Path], textures: Sequence[Path], destination: Path
) -> dict[Path, Path]:
    destinations: dict[Path, Path] = {}
    layer_dir = destination / "layers"
    texture_dir = destination / "textures"
    layer_dir.mkdir(parents=True, exist_ok=True)
    texture_dir.mkdir(parents=True, exist_ok=True)

    for path in layers:
        destinations[path] = layer_dir / path.name
    for texture in textures:
        destinations[texture] = texture_dir / texture.name
    return destinations


def _calculate_version_hash(artifacts: Iterable[BundleArtifact]) -> str:
    digest = hashlib.sha256()
    for artifact in sorted(artifacts, key=lambda item: str(item.bundled_path)):
        digest.update(artifact.sha256.encode())
        digest.update(str(artifact.bundled_path).encode())
    return digest.hexdigest()


def bundle_usd(
    root_layer: Path,
    destination: Path,
    *,
    variants: Mapping[str, str] | None = None,
) -> BundleManifest:
    """Create a self contained USD bundle with rewritten dependencies."""

    layer_content: dict[Path, str] = {}
    layers: set[Path] = set()
    textures: set[Path] = set()

    _collect_layers(
        root_layer,
        variant_overrides=variants or {},
        seen=layers,
        layer_content=layer_content,
        textures=textures,
    )

    destination_map = _build_destination_map(
        sorted(layers), sorted(textures), destination
    )

    artifacts: list[BundleArtifact] = []
    for layer_path in sorted(layers):
        destination_layer = destination_map[layer_path]
        rewritten = _rewrite_asset_references(
            layer_content[layer_path],
            source_layer=layer_path,
            destination_layer=destination_layer,
            destination_map=destination_map,
        )
        destination_layer.write_text(rewritten, encoding="utf-8")
        digest = _sha256_of(destination_layer)
        artifacts.append(
            BundleArtifact(
                kind="layer",
                source=layer_path,
                bundled_path=destination_layer.relative_to(destination),
                sha256=digest,
            )
        )

    for texture in sorted(textures):
        destination_texture = destination_map[texture]
        destination_texture.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(texture, destination_texture)
        digest = _sha256_of(destination_texture)
        artifacts.append(
            BundleArtifact(
                kind="texture",
                source=texture,
                bundled_path=destination_texture.relative_to(destination),
                sha256=digest,
            )
        )

    version_hash = _calculate_version_hash(artifacts)
    manifest = BundleManifest(
        root_layer=destination_map[root_layer.resolve()].relative_to(destination),
        version_hash=version_hash,
        artifacts=tuple(artifacts),
    )

    manifest_path = destination / _MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")

    return manifest


__all__ = ["BundleArtifact", "BundleManifest", "BundleError", "bundle_usd"]
