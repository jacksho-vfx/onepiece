"""3D model optimization handler."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from libraries.pipeline.ingest.detection import ASSET_TYPE_MODEL, normalize_extension
from libraries.pipeline.optimize.handlers.base import HandlerContext, HandlerResult
from libraries.pipeline.optimize.report import OptimizationStep

SUPPORTED_EXTENSIONS = {
    ".fbx",
    ".obj",
    ".gltf",
    ".glb",
    ".abc",
    ".usd",
    ".usda",
    ".usdc",
    ".blend",
    ".ma",
    ".mb",
}


@dataclass(frozen=True)
class ModelMetrics:
    polycount: int | None = None
    texture_count: int | None = None
    texture_resolution: list[tuple[int, int]] | None = None


def _find_model_files(payload_root: Path) -> list[Path]:
    if payload_root.is_file():
        return [payload_root]
    return sorted(
        [
            path
            for path in payload_root.rglob("*")
            if normalize_extension(path) in SUPPORTED_EXTENSIONS
        ]
    )


def _parse_obj_polycount(path: Path) -> int:
    count = 0
    for line in path.read_text(errors="ignore").splitlines():
        if line.startswith("f "):
            count += 1
    return count


def _parse_gltf_polycount(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    meshes = payload.get("meshes", [])
    if not isinstance(meshes, list):
        return None
    count = 0
    for mesh in meshes:
        primitives = mesh.get("primitives", []) if isinstance(mesh, dict) else []
        if isinstance(primitives, list):
            count += len(primitives)
    return count


def _extract_obj_textures(path: Path) -> list[Path]:
    textures: list[Path] = []
    for line in path.read_text(errors="ignore").splitlines():
        if line.lower().startswith("mtllib "):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                mtl_path = path.parent / parts[1].strip()
                if mtl_path.exists():
                    textures.extend(_extract_mtl_textures(mtl_path))
    return textures


def _extract_mtl_textures(path: Path) -> list[Path]:
    textures: list[Path] = []
    for line in path.read_text(errors="ignore").splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0].lower().startswith("map_") and len(tokens) > 1:
            tex_path = path.parent / tokens[-1]
            textures.append(tex_path)
    return textures


def _extract_gltf_textures(path: Path) -> list[Path]:
    textures: list[Path] = []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return textures
    if not isinstance(payload, dict):
        return textures
    images = payload.get("images", [])
    if not isinstance(images, list):
        return textures
    for image in images:
        if not isinstance(image, dict):
            continue
        uri = image.get("uri")
        if isinstance(uri, str):
            textures.append(path.parent / uri)
    return textures


def _collect_texture_paths(model_path: Path) -> list[Path]:
    ext = normalize_extension(model_path)
    if ext == ".obj":
        return _extract_obj_textures(model_path)
    if ext == ".gltf":
        return _extract_gltf_textures(model_path)
    return []


def _copy_textures(
    textures: Iterable[Path],
    *,
    payload_root: Path,
    output_root: Path,
    result: HandlerResult,
) -> None:
    for texture in sorted(set(textures)):
        if not texture.exists():
            result.warnings.append(f"Missing texture reference: {texture}")
            continue
        if payload_root.is_dir():
            try:
                relative = texture.relative_to(payload_root)
            except ValueError:
                relative = Path(texture.name)
        else:
            relative = Path(texture.name)
        destination = output_root / "textures" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(texture, destination)
        result.output_files.append(destination)


def _measure_metrics(model_path: Path) -> ModelMetrics:
    ext = normalize_extension(model_path)
    if ext == ".obj":
        return ModelMetrics(polycount=_parse_obj_polycount(model_path))
    if ext == ".gltf":
        return ModelMetrics(polycount=_parse_gltf_polycount(model_path))
    return ModelMetrics()


def _resolve_usd_converter(extension: str) -> list[str] | None:
    converters = {
        ".gltf": "usd_from_gltf",
        ".glb": "usd_from_gltf",
        ".fbx": "usd_from_fbx",
        ".obj": "usd_from_obj",
    }
    command = converters.get(extension)
    if command is None:
        return None
    return [command]


def _convert_to_usd(
    model_path: Path,
    output_path: Path,
    result: HandlerResult,
    settings: dict[str, Any],
) -> None:
    extension = normalize_extension(model_path)
    target_ext = f".{settings.get('usd_format', 'usdc')}"
    converter = _resolve_usd_converter(extension)
    if extension in {".usd", ".usda", ".usdc"}:
        if output_path.suffix != target_ext:
            converter = ["usdcat"]
    if converter is None:
        result.steps.append(
            OptimizationStep(
                name="convert_to_usd",
                status="skipped",
                detail="USD converter not available for this format.",
            )
        )
        result.warnings.append("USD conversion skipped: no converter available.")
        return
    import shutil as _shutil

    if _shutil.which(converter[0]) is None:
        result.steps.append(
            OptimizationStep(
                name="convert_to_usd",
                status="skipped",
                detail=f"Missing converter tool '{converter[0]}'.",
            )
        )
        result.warnings.append("USD conversion skipped: converter tool not available.")
        return
    import subprocess

    args = converter + [str(model_path), str(output_path)]
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        result.steps.append(
            OptimizationStep(
                name="convert_to_usd",
                status="error",
                detail=exc.stderr.strip() or "USD conversion failed.",
            )
        )
        result.errors.append("USD conversion failed.")
        return
    result.steps.append(OptimizationStep(name="convert_to_usd", status="ok"))
    result.output_files.append(output_path)


def optimize_model(context: HandlerContext) -> HandlerResult:
    result = HandlerResult()
    model_files = _find_model_files(context.payload_root)
    if not model_files:
        result.steps.append(
            OptimizationStep(
                name="detect_model",
                status="skipped",
                detail="No supported model files found.",
            )
        )
        return result

    model_path = model_files[0]
    output_root = context.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    output_model = output_root / model_path.name

    settings = context.settings
    steps = {
        "clean_geometry": settings.get("clean_geometry", False),
        "merge_materials": settings.get("merge_materials", False),
        "fix_normals": settings.get("fix_normals", False),
        "strip_junk_nodes": settings.get("strip_junk_nodes", False),
        "generate_lods": settings.get("generate_lods", False),
        "decimate": settings.get("decimate", False),
        "normalize_scene": settings.get("normalize_scene", False),
    }
    for name, enabled in steps.items():
        if name == "generate_lods" and enabled:
            lod_targets = settings.get("lod_targets", [60, 30])
            lod_root = output_root / "lods"
            for index in range(3):
                lod_dir = lod_root / f"lod{index}"
                lod_dir.mkdir(parents=True, exist_ok=True)
                lod_path = lod_dir / model_path.name
                shutil.copy2(model_path, lod_path)
                result.output_files.append(lod_path)
            result.steps.append(
                OptimizationStep(
                    name="generate_lods",
                    status="ok",
                    detail=f"Generated placeholder LODs with targets {lod_targets}.",
                )
            )
            result.warnings.append("LOD decimation tool unavailable; copied base mesh.")
            continue
        status = "skipped"
        detail = "Tooling not configured; no-op."
        if not enabled:
            detail = "Disabled by configuration."
        result.steps.append(OptimizationStep(name=name, status=status, detail=detail))

    if settings.get("convert_to_usd"):
        output_model = (
            output_root / f"{model_path.stem}.{settings.get('usd_format', 'usdc')}"
        )
        _convert_to_usd(model_path, output_model, result, settings)
    else:
        shutil.copy2(model_path, output_model)
        result.output_files.append(output_model)
        result.steps.append(OptimizationStep(name="copy_model", status="ok"))

    metrics = _measure_metrics(model_path)
    textures = _collect_texture_paths(model_path)
    if textures:
        metrics = ModelMetrics(
            polycount=metrics.polycount,
            texture_count=len(set(textures)),
            texture_resolution=None,
        )
    result.metrics.update(
        {
            "polycount": metrics.polycount,
            "texture_count": metrics.texture_count,
            "texture_resolution": metrics.texture_resolution,
        }
    )

    if settings.get("copy_textures"):
        _copy_textures(
            textures,
            payload_root=context.payload_root,
            output_root=output_root,
            result=result,
        )
        result.steps.append(OptimizationStep(name="copy_textures", status="ok"))
    else:
        result.steps.append(
            OptimizationStep(
                name="copy_textures",
                status="skipped",
                detail="Disabled by configuration.",
            )
        )

    if settings.get("preview_proxy"):
        result.steps.append(
            OptimizationStep(
                name="preview_proxy",
                status="skipped",
                detail="Preview proxy generation not implemented.",
            )
        )

    result.metrics["model_path"] = str(model_path)
    return result


def supports(types: Iterable[str]) -> bool:
    return ASSET_TYPE_MODEL in set(types)
