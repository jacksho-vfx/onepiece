"""Configuration loaders for asset optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True)
class DeadlineConfig:
    pool: str | None = None
    group: str | None = None
    priority: int | None = None
    extra_info: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VariantConfig:
    name: str
    enabled: bool = True
    handlers: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizationConfig:
    schema_version: int
    variants: dict[str, VariantConfig]
    deadline: DeadlineConfig


_DEFAULT_SCHEMA_VERSION = 1


def _deep_merge(left: dict[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _default_variant_payloads() -> dict[str, dict[str, Any]]:
    return {
        "optimized": {
            "enabled": True,
            "handlers": {
                "3d": {
                    "clean_geometry": True,
                    "merge_materials": True,
                    "fix_normals": True,
                    "strip_junk_nodes": True,
                    "generate_lods": False,
                    "lod_targets": [60, 30],
                    "decimate": False,
                    "max_error": 0.01,
                    "normalize_scene": True,
                    "up_axis": "Y",
                    "unit_scale": 1.0,
                    "pivot": "origin",
                    "copy_textures": True,
                    "generate_mips": False,
                },
                "texture": {
                    "resize_by_tag": {},
                    "resize_max": None,
                    "format": None,
                    "generate_mips": False,
                    "mip_levels": 3,
                    "tile": False,
                    "expect_alpha": None,
                    "expect_bit_depth": None,
                },
                "cache": {
                    "proxy": False,
                    "validate_frames": True,
                },
            },
        },
        "usd": {
            "enabled": True,
            "handlers": {
                "3d": {
                    "convert_to_usd": True,
                    "usd_format": "usdc",
                    "package_mode": "flatten",
                    "copy_textures": True,
                    "preview_proxy": False,
                }
            },
        },
        "proxy": {
            "enabled": True,
            "handlers": {
                "texture": {
                    "resize_by_tag": {},
                    "resize_max": 1024,
                    "format": "png",
                    "generate_mips": True,
                    "mip_levels": 2,
                    "tile": False,
                },
                "cache": {
                    "proxy": True,
                    "validate_frames": True,
                },
            },
        },
    }


def _load_variant_configs(raw: Mapping[str, Any]) -> dict[str, VariantConfig]:
    variants: dict[str, VariantConfig] = {}
    raw_variants = raw.get("variants", {})
    for name, variant_data in raw_variants.items():
        if not isinstance(variant_data, Mapping):
            continue
        handlers = variant_data.get("handlers", {})
        variants[str(name)] = VariantConfig(
            name=str(name),
            enabled=bool(variant_data.get("enabled", True)),
            handlers=dict(handlers) if isinstance(handlers, Mapping) else {},
        )
    return variants


def _load_deadline_config(raw: Mapping[str, Any]) -> DeadlineConfig:
    deadline_raw = raw.get("deadline", {})
    if not isinstance(deadline_raw, Mapping):
        deadline_raw = {}
    return DeadlineConfig(
        pool=deadline_raw.get("pool"),
        group=deadline_raw.get("group"),
        priority=deadline_raw.get("priority"),
        extra_info=(
            dict(deadline_raw.get("extra_info", {}))
            if isinstance(deadline_raw.get("extra_info"), Mapping)
            else {}
        ),
    )


def _default_payload() -> dict[str, Any]:
    return {
        "schema_version": _DEFAULT_SCHEMA_VERSION,
        "variants": _default_variant_payloads(),
        "deadline": {},
    }


def load_optimize_config(
    *,
    project_root: Path,
    profile_data: Mapping[str, Any] | None = None,
) -> OptimizationConfig:
    payload = _default_payload()
    config_path = project_root / ".pipeline" / "optimize_config.yaml"
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text()) or {}
        if not isinstance(raw, Mapping):
            raise ValueError("Optimization config must be a mapping")
        payload = _deep_merge(payload, raw)
    if profile_data and isinstance(profile_data.get("optimize"), Mapping):
        payload = _deep_merge(payload, profile_data.get("optimize", {}))
    schema_version = int(payload.get("schema_version", _DEFAULT_SCHEMA_VERSION))
    if schema_version != _DEFAULT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported optimize config schema version: {schema_version}"
        )
    variants = _load_variant_configs(payload)
    deadline = _load_deadline_config(payload)
    return OptimizationConfig(
        schema_version=schema_version,
        variants=variants,
        deadline=deadline,
    )
