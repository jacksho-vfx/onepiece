"""Texture and image optimization handler."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import shutil
from typing import Any, Iterable

from libraries.pipeline.ingest.detection import ASSET_TYPE_IMAGE, ASSET_TYPE_TEXTURE
from libraries.pipeline.optimize.handlers.base import HandlerContext, HandlerResult
from libraries.pipeline.optimize.report import OptimizationStep


SUPPORTED_EXTENSIONS = {".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".tx"}


@dataclass(frozen=True)
class TextureMetrics:
    count: int
    resolutions: list[tuple[int, int]]
    has_alpha: bool | None = None
    bit_depth: int | None = None


def _find_texture_files(payload_root: Path) -> list[Path]:
    if payload_root.is_file():
        return (
            [payload_root]
            if payload_root.suffix.lower() in SUPPORTED_EXTENSIONS
            else []
        )
    return sorted(
        [
            path
            for path in payload_root.rglob("*")
            if path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
    )


def _target_size(tags: set[str], settings: dict[str, Any]) -> int | None:
    resize_by_tag = settings.get("resize_by_tag", {})
    if isinstance(resize_by_tag, dict):
        for tag, size in resize_by_tag.items():
            if tag in tags:
                return int(size)
    if settings.get("resize_max"):
        return int(settings["resize_max"])
    return None


def _load_pillow() -> Any | None:
    if importlib.util.find_spec("PIL") is None:
        return None
    from PIL import Image

    return Image


def _compute_bit_depth(image: Any) -> int | None:
    if image.mode in {"RGB", "RGBA"}:
        return 8
    if image.mode in {"I;16", "I;16B", "I;16L"}:
        return 16
    return None


def _resize_image(image: Any, max_size: int) -> Any:
    width, height = image.size
    scale = max(width, height) / max_size
    if scale <= 1:
        return image
    new_size = (int(width / scale), int(height / scale))
    Image = _load_pillow()
    resample = Image.LANCZOS if Image is not None else None
    if resample is None:
        return image.resize(new_size)
    return image.resize(new_size, resample)


def _save_image(image: Any, path: Path, format_hint: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_hint:
        image.save(path, format=format_hint.upper())
    else:
        image.save(path)


def _generate_mips(image: Any, base_path: Path, levels: int) -> list[Path]:
    mip_paths: list[Path] = []
    Image = _load_pillow()
    if Image is None:
        return []
    current = image
    for level in range(1, levels + 1):
        width, height = current.size
        if width <= 1 or height <= 1:
            break
        current = current.resize(
            (max(1, width // 2), max(1, height // 2)), Image.LANCZOS
        )
        mip_path = base_path.with_stem(f"{base_path.stem}_mip{level}")
        _save_image(current, mip_path, base_path.suffix.lstrip("."))
        mip_paths.append(mip_path)
    return mip_paths


def optimize_textures(context: HandlerContext) -> HandlerResult:
    result = HandlerResult()
    textures = _find_texture_files(context.payload_root)
    if not textures:
        result.steps.append(
            OptimizationStep(
                name="detect_textures",
                status="skipped",
                detail="No texture files detected.",
            )
        )
        return result

    output_root = context.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    settings = context.settings
    target = _target_size(context.tags, settings)
    format_hint = settings.get("format")
    expect_alpha = settings.get("expect_alpha")
    expect_bit_depth = settings.get("expect_bit_depth")
    generate_mips = settings.get("generate_mips", False)
    mip_levels = int(settings.get("mip_levels", 0) or 0)
    if settings.get("tile"):
        result.steps.append(
            OptimizationStep(
                name="tile_textures",
                status="skipped",
                detail="Tiled texture output not implemented.",
            )
        )

    resolutions: list[tuple[int, int]] = []
    has_alpha_values: list[bool] = []
    bit_depth_values: list[int] = []

    Image = _load_pillow()
    for texture in textures:
        relative = (
            texture.relative_to(context.payload_root)
            if context.payload_root.is_dir()
            else Path(texture.name)
        )
        output_path = output_root / relative
        if format_hint:
            output_path = output_path.with_suffix(f".{format_hint}")
        if Image is None:
            shutil.copy2(texture, output_path)
            result.output_files.append(output_path)
            result.steps.append(
                OptimizationStep(
                    name="copy_texture",
                    status="ok",
                    detail="Pillow unavailable; copied texture.",
                )
            )
            continue
        with Image.open(texture) as image:
            if target:
                image = _resize_image(image, target)
            _save_image(image, output_path, format_hint)
            result.output_files.append(output_path)
            resolutions.append(image.size)
            if image.mode in {"RGBA", "LA"}:
                has_alpha_values.append(True)
            else:
                has_alpha_values.append(False)
            bit_depth = _compute_bit_depth(image)
            if bit_depth is not None:
                bit_depth_values.append(bit_depth)
            if generate_mips and mip_levels:
                result.output_files.extend(
                    _generate_mips(image, output_path, mip_levels)
                )

    if expect_alpha is not None:
        if any(has_alpha_values) != bool(expect_alpha):
            result.warnings.append("Alpha channel expectation mismatch.")
    if expect_bit_depth is not None and bit_depth_values:
        if any(depth != int(expect_bit_depth) for depth in bit_depth_values):
            result.warnings.append("Bit depth expectation mismatch.")

    result.metrics.update(
        {
            "texture_count": len(textures),
            "resolutions": resolutions,
            "has_alpha": any(has_alpha_values) if has_alpha_values else None,
            "bit_depth": bit_depth_values[0] if bit_depth_values else None,
        }
    )
    result.steps.append(OptimizationStep(name="optimize_textures", status="ok"))
    return result


def supports(types: Iterable[str]) -> bool:
    return bool({ASSET_TYPE_TEXTURE, ASSET_TYPE_IMAGE}.intersection(types))
