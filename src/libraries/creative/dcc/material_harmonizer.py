"""Utilities for translating USDShade networks into DCC-specific materials.

The material harmonizer ingests simplified USDShade networks (as strings or
pre-parsed mappings) and emits DCC-friendly descriptions using configurable
node templates. Texture relinking and colorspace metadata preservation are
handled during translation to keep materials consistent across applications.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class UsdShadeParseError(RuntimeError):
    """Raised when a USDShade payload cannot be interpreted."""


@dataclass(frozen=True)
class UsdTexture:
    name: str
    path: Path
    colorspace: str | None = None


@dataclass
class UsdShadeNetwork:
    material_name: str
    surface_shader: str
    textures: list[UsdTexture]
    raw_payload: str | None = None
    asset_root: Path | None = None

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable snapshot for regression comparison."""

        return {
            "material": self.material_name,
            "surface": self.surface_shader,
            "textures": [
                {
                    "name": texture.name,
                    "file": str(texture.path),
                    "colorspace": texture.colorspace,
                }
                for texture in self.textures
            ],
        }


@dataclass(frozen=True)
class DccTemplate:
    name: str
    surface_node: str
    texture_node: str
    colorspace_attribute: str


@dataclass
class MaterialTranslation:
    material_name: str
    dcc: str
    template: DccTemplate
    textures: list[UsdTexture]
    nodes: list[dict[str, Any]]
    connections: list[dict[str, str]]

    def to_usd_template(self) -> dict[str, Any]:
        """Return a USD-like mapping preserving relinked textures and color tags."""

        return {
            "material": self.material_name,
            "surface": self.template.surface_node,
            "textures": [
                {
                    "name": texture.name,
                    "file": str(texture.path),
                    "colorspace": texture.colorspace,
                }
                for texture in self.textures
            ],
        }


_DEFAULT_TEMPLATES: dict[str, DccTemplate] = {
    "cinema4d": DccTemplate(
        name="cinema4d",
        surface_node="C4DStandardSurface",
        texture_node="C4DTextureSampler",
        colorspace_attribute="color_profile",
    ),
    "unreal": DccTemplate(
        name="unreal",
        surface_node="UnrealMaterial",
        texture_node="TextureSample",
        colorspace_attribute="texture_color_space",
    ),
    "nuke": DccTemplate(
        name="nuke",
        surface_node="NukeMaterialBuilder",
        texture_node="Read",
        colorspace_attribute="colorspace",
    ),
}


class MaterialHarmonizer:
    """Translate USDShade networks into DCC-specific material descriptions."""

    def __init__(self, templates: Mapping[str, DccTemplate] | None = None):
        self.templates = dict(_DEFAULT_TEMPLATES)
        if templates:
            self.templates.update(templates)

    def parse_usdshade(
        self, payload: str | Path | Mapping[str, Any]
    ) -> UsdShadeNetwork:
        """Parse a simplified USDShade payload.

        The parser accepts either a mapping pre-populated with material data or a
        string containing a small USD ASCII fragment with Shader definitions.
        Only the data required for template translation (material name, surface
        shader id, texture files, and colorspace tags) is extracted.
        """

        if isinstance(payload, Mapping):
            return self._network_from_mapping(payload)
        if isinstance(payload, Path):
            text = payload.read_text()
            return self._network_from_text(text, asset_root=payload.parent)
        if isinstance(payload, str):
            return self._network_from_text(payload)
        msg = f"Unsupported USDShade payload type: {type(payload)!r}"
        raise UsdShadeParseError(msg)

    def translate(
        self,
        payload: str | Path | Mapping[str, Any],
        targets: Iterable[str] = ("cinema4d", "unreal", "nuke"),
        texture_search_paths: Sequence[Path] | None = None,
    ) -> list[MaterialTranslation]:
        """Translate the USDShade payload into multiple DCC targets."""

        network = self.parse_usdshade(payload)
        relinked = self._relink_textures(network, texture_search_paths or ())
        translations: list[MaterialTranslation] = []
        for target in targets:
            template = self.templates.get(target)
            if template is None:
                msg = f"No DCC template registered for '{target}'"
                raise KeyError(msg)
            translations.append(self._translate_for_dcc(relinked, template))
        return translations

    def _network_from_mapping(self, data: Mapping[str, Any]) -> UsdShadeNetwork:
        try:
            material_name = str(data["material"])
            surface_shader = str(data["surface"])
            textures: list[UsdTexture] = []
            for entry in data.get("textures", []):
                textures.append(
                    UsdTexture(
                        name=str(entry["name"]),
                        path=Path(entry["file"]),
                        colorspace=entry.get("colorspace"),
                    )
                )
        except KeyError as exc:  # pragma: no cover - defensive clarity
            msg = f"USDShade mapping missing required key: {exc!s}"
            raise UsdShadeParseError(msg) from exc
        return UsdShadeNetwork(
            material_name=material_name,
            surface_shader=surface_shader,
            textures=textures,
            raw_payload=None,
            asset_root=None,
        )

    def _network_from_text(
        self, text: str, asset_root: Path | None = None
    ) -> UsdShadeNetwork:
        material_name = self._extract_material_name(text)
        surface_shader = self._extract_surface_shader(text)
        textures = list(self._extract_textures(text))
        if not textures:
            msg = "No textures found in USDShade payload"
            raise UsdShadeParseError(msg)
        return UsdShadeNetwork(
            material_name=material_name,
            surface_shader=surface_shader,
            textures=textures,
            raw_payload=text,
            asset_root=asset_root,
        )

    def _extract_material_name(self, text: str) -> str:
        match = re.search(r"def\s+Material\s+\"(?P<name>[^\"]+)\"", text)
        if match:
            return match.group("name")
        msg = "Material definition not found in USDShade payload"
        raise UsdShadeParseError(msg)

    def _extract_surface_shader(self, text: str) -> str:
        match = re.search(r"info:id\s*=\s*\"(?P<shader>[^\"]+)\"", text)
        if match:
            return match.group("shader")
        msg = "Surface shader id not found in USDShade payload"
        raise UsdShadeParseError(msg)

    def _extract_textures(self, text: str) -> Iterable[UsdTexture]:
        shader_pattern = re.compile(
            r"def\s+Shader\s+\"(?P<name>[^\"]+)\"\s*\{(?P<body>.*?)\}", re.DOTALL
        )
        for shader_match in shader_pattern.finditer(text):
            shader_body = shader_match.group("body")
            shader_id_match = re.search(
                r"info:id\s*=\s*\"(?P<id>[^\"]+)\"", shader_body
            )
            if not shader_id_match:
                continue
            shader_id = shader_id_match.group("id")
            if "UsdUVTexture" not in shader_id:
                continue
            file_match = re.search(r"inputs:file\s*=\s*@(?P<file>[^@]+)@", shader_body)
            if not file_match:
                continue
            path = Path(file_match.group("file"))
            cs_match = re.search(
                r"inputs:sourceColorSpace\s*=\s*\"(?P<cs>[^\"]+)\"",
                shader_body,
            )
            colorspace = cs_match.group("cs") if cs_match else None
            name = shader_match.group("name")
            yield UsdTexture(name=name, path=path, colorspace=colorspace)

    def _relink_textures(
        self, network: UsdShadeNetwork, search_paths: Sequence[Path]
    ) -> UsdShadeNetwork:
        relinked_textures: list[UsdTexture] = []
        search_order: list[Path] = []
        if network.asset_root:
            search_order.append(network.asset_root)
        search_order.extend(Path(p) for p in search_paths)
        for texture in network.textures:
            resolved_path = self._resolve_texture_path(texture.path, search_order)
            relinked_textures.append(
                UsdTexture(
                    name=texture.name,
                    path=resolved_path,
                    colorspace=texture.colorspace,
                )
            )
        return UsdShadeNetwork(
            material_name=network.material_name,
            surface_shader=network.surface_shader,
            textures=relinked_textures,
            raw_payload=network.raw_payload,
            asset_root=network.asset_root,
        )

    def _resolve_texture_path(
        self, original: Path, search_paths: Sequence[Path]
    ) -> Path:
        if original.is_absolute() and original.exists():
            return original
        if not original.is_absolute() and search_paths:
            for root in search_paths:
                candidate = Path(root) / original.name
                if candidate.exists():
                    return candidate
        return original

    def _translate_for_dcc(
        self, network: UsdShadeNetwork, template: DccTemplate
    ) -> MaterialTranslation:
        nodes: list[dict[str, Any]] = [
            {
                "name": f"{network.material_name}_surface",
                "type": template.surface_node,
                "from_shader": network.surface_shader,
            }
        ]
        connections: list[dict[str, str]] = []
        for texture in network.textures:
            texture_node_name = f"{texture.name.lower()}_{template.texture_node}"
            nodes.append(
                {
                    "name": texture_node_name,
                    "type": template.texture_node,
                    "file": str(texture.path),
                    template.colorspace_attribute: texture.colorspace,
                }
            )
            connections.append(
                {
                    "from": texture_node_name,
                    "to": f"{network.material_name}_surface",
                    "purpose": "diffuseColor",
                }
            )
        return MaterialTranslation(
            material_name=network.material_name,
            dcc=template.name,
            template=template,
            textures=network.textures,
            nodes=nodes,
            connections=connections,
        )


__all__ = [
    "DccTemplate",
    "MaterialHarmonizer",
    "MaterialTranslation",
    "UsdShadeNetwork",
    "UsdShadeParseError",
    "UsdTexture",
]
