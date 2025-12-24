from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from libraries.creative.dcc.lighting_presets import LightingPreset, load_lighting_preset


@dataclass(frozen=True)
class TurntableTemplates:
    """Companion templates for consuming a generated turntable stage."""

    unreal_level_sequence: dict[str, object]
    nuke_read: str
    nuke_write: str


@dataclass(frozen=True)
class TurntableStage:
    """Description of a generated turntable package."""

    stage_path: Path
    camera_path: str
    frame_range: tuple[int, int]
    fps: int
    templates: TurntableTemplates


def _relative_to_base(path: Path, base_dir: Path) -> Path:
    try:
        return path.relative_to(base_dir)
    except ValueError:
        return Path(os.path.relpath(path, base_dir))


def _format_sublayers(layers: Iterable[Path]) -> str:
    formatted = []
    for layer in layers:
        formatted.append(f"        @{layer.as_posix()}@")
    return "\n".join(formatted)


def _build_unreal_template(
    stage_path: Path, camera_path: str, frame_range: tuple[int, int], fps: int
) -> dict[str, object]:
    start, end = frame_range
    return {
        "sequence_name": "Turntable",
        "stage": stage_path.as_posix(),
        "camera_prim": camera_path,
        "fps": fps,
        "frame_range": {"start": start, "end": end},
        "tracks": [
            {
                "type": "LevelVisibility",
                "asset": stage_path.as_posix(),
                "start": start,
                "end": end,
            },
            {
                "type": "CameraCut",
                "camera": camera_path,
                "start": start,
                "end": end,
            },
        ],
    }


def _build_nuke_read_template(
    stage_path: Path, frame_range: tuple[int, int], camera_path: str
) -> str:
    start, end = frame_range
    return (
        "# Turntable read template\n"
        "ReadGeo2 {\n"
        f' file "{stage_path.as_posix()}"\n'
        f" first {start}\n"
        f" last {end}\n"
        "}\n\n"
        "Camera2 {\n"
        f' file "{stage_path.as_posix()}"\n'
        " read_from_file true\n"
        f' camera_path "{camera_path}"\n'
        "}\n"
    )


def _build_nuke_write_template(stage_path: Path, frame_range: tuple[int, int]) -> str:
    start, end = frame_range
    return (
        "# Turntable write template\n"
        "Write {\n"
        ' file "renders/turntable.%04d.exr"\n'
        f' input_stage "{stage_path.as_posix()}"\n'
        f" first {start}\n"
        f" last {end}\n"
        ' datatype "16 bit half"\n'
        "}\n"
    )


def _build_stage_content(
    *,
    asset_layer: Path,
    lighting_preset: LightingPreset,
    stage_dir: Path,
    frame_range: tuple[int, int],
    fps: int,
    backdrop_radius: float,
    camera_distance: float,
    camera_path: str,
) -> str:
    start, end = frame_range
    lighting_layers = _format_sublayers(
        _relative_to_base(layer, stage_dir) for layer in lighting_preset.layer_stack
    )
    referenced_asset = _relative_to_base(asset_layer, stage_dir).as_posix()
    camera_name = camera_path.rsplit("/", maxsplit=1)[-1] or "RenderCamera"
    return f"""#usda 1.0
(
    upAxis = \"Y\"
    metersPerUnit = 1
    timeCodesPerSecond = {fps}
    startTimeCode = {start}
    endTimeCode = {end}
    subLayers = [
{lighting_layers}
    ]
)

def Xform \"Turntable\" {{
    def Xform \"Asset\" (
        prepend references = @{referenced_asset}@
    ) {{}}

    def Scope \"Backdrop\" {{
        def Sphere \"StudioDome\" {{
            double radius = {backdrop_radius}
            color3f displayColor = (0.18, 0.18, 0.18)
        }}
    }}

    def Camera \"{camera_name}\" {{
        float focalLength = 50
        float horizontalAperture = 20.955
        float verticalAperture = 11.772
        float3 xformOp:translate = (0, 1.5, {camera_distance})
        double xformOp:rotateY.timeSamples = {{
            {start}: 0
            {end}: 360
        }}
        uniform token[] xformOpOrder = [\"xformOp:translate\", \"xformOp:rotateY\"]
    }}
}}
"""


def generate_turntable_stage(
    asset_layer: Path,
    output_dir: Path,
    *,
    lighting_preset: str = "studio",
    exposure: str = "neutral",
    stage_name: str = "turntable.usda",
    frame_range: tuple[int, int] = (1001, 1120),
    fps: int = 24,
    backdrop_radius: float = 8.0,
    camera_distance: float = 6.0,
    camera_path: str = "/Turntable/RenderCamera",
) -> TurntableStage:
    """Create a USD turntable stage plus downstream templates.

    The generated stage orbits the camera 360 degrees across the provided frame
    range, layers in the requested lighting preset, and includes a neutral
    studio backdrop. Companion Unreal and Nuke templates point at the generated
    stage and adopt the same timing, so the turntable can be consumed without
    manual retiming.
    """

    asset_layer = Path(asset_layer)
    output_dir = Path(output_dir)
    if not asset_layer.exists():
        raise FileNotFoundError(asset_layer)

    output_dir.mkdir(parents=True, exist_ok=True)
    lighting = load_lighting_preset(lighting_preset, exposure=exposure)
    stage_path = output_dir / stage_name

    payload = _build_stage_content(
        asset_layer=asset_layer,
        lighting_preset=lighting,
        stage_dir=stage_path.parent,
        frame_range=frame_range,
        fps=fps,
        backdrop_radius=backdrop_radius,
        camera_distance=camera_distance,
        camera_path=camera_path,
    )
    stage_path.write_text(payload, encoding="utf-8")

    templates = TurntableTemplates(
        unreal_level_sequence=_build_unreal_template(
            stage_path, camera_path, frame_range, fps
        ),
        nuke_read=_build_nuke_read_template(stage_path, frame_range, camera_path),
        nuke_write=_build_nuke_write_template(stage_path, frame_range),
    )

    return TurntableStage(
        stage_path=stage_path,
        camera_path=camera_path,
        frame_range=frame_range,
        fps=fps,
        templates=templates,
    )


__all__ = ["TurntableStage", "TurntableTemplates", "generate_turntable_stage"]
