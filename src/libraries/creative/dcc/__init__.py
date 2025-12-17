"""Helpers for working with Digital Content Creation (DCC) tools."""

from libraries.creative.dcc.client import (
    BaseDCCClient,
    BlenderClient,
    HoudiniClient,
    Cinema4DClient,
    MaxClient,
    MayaClient,
    NukeClient,
    VrayClient,
)
from libraries.creative.dcc.dcc_client import SupportedDCC, open_scene
from libraries.creative.dcc.enums import DCC
from libraries.creative.dcc.lighting_presets import (
    LightingPreset,
    find_preset_root,
    list_lighting_presets,
    load_lighting_preset,
)
from libraries.creative.dcc.codex import (
    CodexTask,
    CROSS_DCC_CODEX_TASKS,
    list_codex_tasks,
)

__all__ = [
    "SupportedDCC",
    "open_scene",
    "DCC",
    "BaseDCCClient",
    "MayaClient",
    "NukeClient",
    "HoudiniClient",
    "BlenderClient",
    "MaxClient",
    "VrayClient",
    "Cinema4DClient",
    "LightingPreset",
    "find_preset_root",
    "list_lighting_presets",
    "load_lighting_preset",
    "CodexTask",
    "CROSS_DCC_CODEX_TASKS",
    "list_codex_tasks",
]
