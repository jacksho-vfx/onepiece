"""Utilities for loading USD lighting preset layers for DCC scripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

_PRESET_MANIFEST: Mapping[str, Mapping[str, str]] = {
    "studio": {
        "neutral": "studio_base.usda",
        "minus_1": "studio_exposure_minus_1.usda",
        "plus_1": "studio_exposure_plus_1.usda",
    },
    "sunset": {
        "neutral": "sunset_base.usda",
        "plus_1": "sunset_exposure_plus_1.usda",
    },
}


@dataclass(frozen=True)
class USDLayer:
    """Lightweight representation of a USD layer for preset composition."""

    path: Path
    sublayers: tuple[Path, ...]
    prim_attributes: dict[str, dict[str, object]]


@dataclass(frozen=True)
class LightingPreset:
    """Resolved lighting preset with flattened composition information."""

    name: str
    exposure: str
    layer_stack: tuple[Path, ...]
    prim_attributes: dict[str, dict[str, object]]


def find_preset_root(root: Path | None = None) -> Path:
    """Return the directory where lighting presets live."""

    if root:
        return Path(root)

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "assets" / "lighting_presets"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "Unable to find assets/lighting_presets from current module"
    )


def list_lighting_presets() -> Mapping[str, Sequence[str]]:
    """Describe available presets and their exposure variants."""

    return {name: tuple(variants.keys()) for name, variants in _PRESET_MANIFEST.items()}


def load_lighting_preset(
    preset: str,
    *,
    exposure: str = "neutral",
    sequence_override: str | Path | None = None,
    root: Path | None = None,
) -> LightingPreset:
    """Load a preset and return a flattened layer stack with composed attributes.

    This helper is intentionally dependency-free so it can be imported inside
    Cinema4D, Nuke, or Unreal scripts. The returned :class:`LightingPreset`
    contains the ordered USD files to sublayer along with the resolved attribute
    values after applying exposure and sequence overrides.
    """

    preset_root = find_preset_root(root)
    preset_root = preset_root.resolve()

    exposures = _PRESET_MANIFEST.get(preset)
    if exposures is None:
        raise ValueError(f"Unknown lighting preset '{preset}'")

    layer_name = exposures.get(exposure)
    if layer_name is None:
        known = ", ".join(sorted(exposures))
        raise ValueError(
            f"Unknown exposure '{exposure}' for preset '{preset}'. Available: {known}"
        )

    primary_layer = preset_root / layer_name
    if not primary_layer.exists():
        raise FileNotFoundError(primary_layer)

    layer_stack = _flatten_layers(primary_layer)

    if sequence_override:
        override_path = Path(sequence_override)
        if not override_path.is_absolute():
            override_path = preset_root / override_path
        layer_stack.extend(_flatten_layers(override_path))

    composed = _compose_attributes(layer_stack)
    ordered_paths = tuple(layer.path for layer in layer_stack)
    return LightingPreset(preset, exposure, ordered_paths, composed)


def _flatten_layers(path: Path, ancestors: set[Path] | None = None) -> list[USDLayer]:
    ancestors = ancestors or set()
    resolved = path.resolve()

    if resolved in ancestors:
        raise ValueError(f"Circular subLayer reference detected for {resolved}")

    layer = _parse_usd_layer(resolved)
    new_ancestors = set(ancestors)
    new_ancestors.add(resolved)

    stack: list[USDLayer] = []
    for sublayer_path in layer.sublayers:
        stack.extend(_flatten_layers(sublayer_path, new_ancestors))

    stack.append(layer)
    return stack


def _parse_usd_layer(path: Path) -> USDLayer:
    content = path.read_text(encoding="utf-8")
    sublayers = tuple(_parse_sublayer_paths(path, content))
    prim_attributes = _parse_prim_attributes(content)
    return USDLayer(path=path, sublayers=sublayers, prim_attributes=prim_attributes)


_SUBLAYER_PATTERN = re.compile(r"@(?P<path>[^@]+)@")
_PRIM_DECLARATION = re.compile(r'^(?:def|over)\s+\w+\s+"(?P<name>[^"]+)"')
_ATTR_DECLARATION = re.compile(
    r"^(?:\w+\s+)?(?P<name>[A-Za-z_][\w]*)\s*=\s*(?P<value>.+)"
)


def _parse_sublayer_paths(base_path: Path, content: str) -> Iterable[Path]:
    header = []
    collecting = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("sublayers") or stripped.startswith("subLayers"):
            collecting = True
        if collecting:
            header.append(stripped)
            if ")" in stripped:
                break

    header_text = "\n".join(header)
    for match in _SUBLAYER_PATTERN.finditer(header_text):
        relative_path = Path(match.group("path"))
        yield (base_path.parent / relative_path).resolve()


def _parse_prim_attributes(content: str) -> dict[str, dict[str, object]]:
    prim_stack: list[str] = []
    attributes: dict[str, dict[str, object]] = {}

    for line in content.splitlines():
        stripped = line.strip()
        prim_decl = _PRIM_DECLARATION.match(stripped)
        if prim_decl:
            prim_stack.append(prim_decl.group("name"))
            prim_path = "/".join(prim_stack)
            attributes.setdefault(prim_path, {})
            continue

        if "}" in stripped and prim_stack:
            closing = stripped.count("}")
            for _ in range(closing):
                if prim_stack:
                    prim_stack.pop()
            continue

        if not prim_stack:
            continue

        attr_decl = _ATTR_DECLARATION.match(stripped)
        if attr_decl:
            prim_path = "/".join(prim_stack)
            attributes.setdefault(prim_path, {})[attr_decl.group("name")] = (
                _parse_value(attr_decl.group("value"))
            )

    return attributes


def _parse_value(raw: str) -> object:
    cleaned = raw.strip().rstrip(";")

    if cleaned.startswith("(") and cleaned.endswith(")"):
        inner = cleaned[1:-1]
        parts = [part.strip() for part in inner.split(",") if part.strip()]
        return tuple(_parse_value(part) for part in parts)

    if cleaned.startswith('"') and cleaned.endswith('"'):
        return cleaned[1:-1]

    lowered = cleaned.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return cleaned


def _compose_attributes(
    layer_stack: Sequence[USDLayer],
) -> dict[str, dict[str, object]]:
    composed: dict[str, dict[str, object]] = {}

    for layer in layer_stack:
        for prim, attrs in layer.prim_attributes.items():
            target = composed.setdefault(prim, {})
            target.update(attrs)

    return composed


__all__ = [
    "LightingPreset",
    "USDLayer",
    "find_preset_root",
    "list_lighting_presets",
    "load_lighting_preset",
]
