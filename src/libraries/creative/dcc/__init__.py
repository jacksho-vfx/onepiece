"""Helpers for working with Digital Content Creation (DCC) tools."""

from libraries.creative.dcc.client import (
    BaseDCCClient,
    BlenderClient,
    Cinema4DClient,
    HoudiniClient,
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
from libraries.creative.dcc.usd_pipeline import (
    LayerRole,
    USDLayerContribution,
    USDShotPlan,
    build_usd_plan,
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
    "USDLayerContribution",
    "USDShotPlan",
    "LayerRole",
    "build_usd_plan",
    "LightingPreset",
    "find_preset_root",
    "list_lighting_presets",
    "load_lighting_preset",
]
