"""Core data structures and constants used by DCC helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, TypeAlias

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | dict[str, "JSONValue"] | list["JSONValue"]

LinkStrategy: TypeAlias = Literal["copy", "hard", "symlink"]


class SupportedDCC(Enum):
    """Enumeration of DCC applications that OnePiece knows how to launch."""

    NUKE = "Nuke"
    MAYA = "Maya"
    BLENDER = "blender"
    HOUDINI = "houdini"
    MAX = "3dsmax"
    VRAY = "vray"
    CINEMA4D = "cinema4d"

    @property
    def command(self) -> str:
        """Return the executable name associated with the DCC."""

        if self is SupportedDCC.MAYA:
            base_command = "maya"
            if os.name == "nt":  # type: ignore[attr-defined]
                return f"{base_command}.exe"
            return base_command

        if self is SupportedDCC.VRAY:
            base_command = "vray"
            if os.name == "nt":  # type: ignore[attr-defined]
                return f"{base_command}.exe"
            return base_command

        return str(self.value)


DCC_PLUGIN_REQUIREMENTS: dict[SupportedDCC, frozenset[str]] = {
    SupportedDCC.NUKE: frozenset({"CaraVR", "OCIO"}),
    SupportedDCC.MAYA: frozenset({"mtoa", "bifrost"}),
    SupportedDCC.BLENDER: frozenset({"cycles"}),
    SupportedDCC.HOUDINI: frozenset({"karma"}),
    SupportedDCC.MAX: frozenset({"vray"}),
    SupportedDCC.VRAY: frozenset({"vray"}),
    SupportedDCC.CINEMA4D: frozenset({"redshift"}),
}


DCC_GPU_REQUIREMENTS: dict[SupportedDCC, str] = {
    SupportedDCC.NUKE: "OpenGL 4.1",
    SupportedDCC.MAYA: "DirectX 11",
    SupportedDCC.BLENDER: "OpenGL 4.3",
    SupportedDCC.HOUDINI: "Vulkan",
    SupportedDCC.MAX: "DirectX 12",
    SupportedDCC.CINEMA4D: "OpenGL 4.5",
}


DCC_ASSET_REQUIREMENTS: dict[SupportedDCC, tuple[str, ...]] = {
    SupportedDCC.NUKE: ("toolsets/init.gizmo", "luts/show_lut.cube"),
    SupportedDCC.MAYA: ("modules/arnold.mod", "scripts/userSetup.mel"),
    SupportedDCC.BLENDER: ("config/startup.blend",),
    SupportedDCC.HOUDINI: ("packages/onepiece.json",),
    SupportedDCC.MAX: ("plugins/onepiece.dlx",),
    SupportedDCC.VRAY: ("config/vray_settings.json",),
    SupportedDCC.CINEMA4D: (
        "plugins/redshift",
        "prefs/cinema4d/shared_prefs.json",
    ),
}


@dataclass
class DCCPluginStatus:
    """Summary of plugin availability for a DCC."""

    required: frozenset[str]
    available: frozenset[str]
    missing: frozenset[str]


@dataclass
class DCCAssetStatus:
    """Summary of asset availability for a packaged scene."""

    required: tuple[Path, ...]
    present: tuple[Path, ...]
    missing: tuple[Path, ...]


@dataclass
class DCCGPUStatus:
    """Summary of GPU compatibility for a DCC package."""

    required: str | None
    detected: str | None
    meets_requirement: bool


@dataclass
class DCCDependencyReport:
    """Aggregate report describing dependency readiness for a DCC package."""

    dcc: SupportedDCC
    plugins: DCCPluginStatus
    assets: DCCAssetStatus
    gpu: DCCGPUStatus | None = None

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when no plugin or asset requirements are missing."""

        gpu_ok = True
        if self.gpu is not None:
            gpu_ok = self.gpu.meets_requirement
        return (not self.plugins.missing) and (not self.assets.missing) and gpu_ok


# ``SupportedDCC.command`` requires :mod:`os` lazily; import here to avoid cycles.
import os  # noqa: E402  (import after class definition for os.name access)

__all__ = [
    "JSONPrimitive",
    "JSONValue",
    "LinkStrategy",
    "SupportedDCC",
    "DCC_PLUGIN_REQUIREMENTS",
    "DCC_GPU_REQUIREMENTS",
    "DCC_ASSET_REQUIREMENTS",
    "DCCPluginStatus",
    "DCCAssetStatus",
    "DCCGPUStatus",
    "DCCDependencyReport",
]
