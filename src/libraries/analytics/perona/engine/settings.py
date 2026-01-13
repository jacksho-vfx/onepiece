"""Configuration helpers for the Perona analytics engine."""

from __future__ import annotations

import logging
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .models import CostModelInput, DEFAULT_CURRENCY

if TYPE_CHECKING:
    from .engine import PeronaEngine

LOGGER = logging.getLogger(__name__)

DEFAULT_BASELINE_COST_INPUT = CostModelInput(
    frame_count=2688,
    average_frame_time_ms=142.0,
    gpu_hourly_rate=8.75,
    gpu_count=64,
    render_hours=0.0,
    render_farm_hourly_rate=5.25,
    storage_gb=12.4,
    storage_rate_per_gb=0.38,
    data_egress_gb=3.8,
    egress_rate_per_gb=0.19,
    misc_costs=220.0,
    currency=DEFAULT_CURRENCY,
)
DEFAULT_TARGET_ERROR_RATE = 0.012
DEFAULT_PNL_BASELINE_COST = 18240.0
DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[1] / "defaults.toml"


@dataclass(frozen=True)
class SettingsLoadResult:
    """Container describing the outcome of loading Perona settings."""

    engine: "PeronaEngine"
    settings_path: Path | None
    warnings: tuple[str, ...] = ()


def _load_settings(
    path: str | os.PathLike[str] | None,
) -> tuple[dict[str, object], Path | None, tuple[str, ...]]:
    """Load configuration data from a TOML file, falling back to defaults."""

    warnings: list[str] = []
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    env_path = os.getenv("PERONA_SETTINGS_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(DEFAULT_SETTINGS_PATH)

    for candidate in candidates:
        expanded = candidate.expanduser()
        try:
            with expanded.open("rb") as handle:
                return tomllib.load(handle), expanded, tuple(warnings)
        except FileNotFoundError as exc:
            message = (
                f"Settings file {expanded} not found ({exc}); falling back to defaults"
            )
            LOGGER.warning(message)
            warnings.append(message)
        except tomllib.TOMLDecodeError as exc:
            message = f"Unable to parse settings file {expanded} ({exc}); falling back to defaults"
            LOGGER.warning(message)
            warnings.append(message)
        except OSError as exc:
            message = f"Unable to read settings file {expanded} ({exc}); falling back to defaults"
            LOGGER.warning(message)
            warnings.append(message)
    return {}, None, tuple(warnings)


def _coerce_int(value: object) -> int | None:
    """Attempt to coerce *value* into an ``int``."""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                float_value = float(text)
            except ValueError:
                return None
            if not math.isfinite(float_value) or not float_value.is_integer():
                return None
            return int(float_value)
    return None


def _coerce_float(value: object) -> float | None:
    """Attempt to coerce *value* into a ``float``."""

    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            result = float(text)
        except ValueError:
            return None
        if not math.isfinite(result):
            return None
        return result
    return None


def _coerce_cost_model_input(
    data: Mapping[str, object] | None, fallback: CostModelInput
) -> CostModelInput:
    source: Mapping[str, object]
    if data is None:
        source = dict[str, object]()
    else:
        source = data

    def _as_int(name: str, default: int) -> int:
        raw_value = source.get(name)
        coerced = _coerce_int(raw_value)
        if coerced is None:
            if raw_value is not None:
                LOGGER.warning(
                    "Ignoring invalid %s override %r; using default %s",
                    f"baseline_cost_input.{name}",
                    raw_value,
                    default,
                )
            return default
        return coerced

    def _as_float(name: str, default: float) -> float:
        coerced = _coerce_float(source.get(name))
        if coerced is None:
            return default
        return coerced

    return CostModelInput(
        frame_count=_as_int("frame_count", fallback.frame_count),
        average_frame_time_ms=_as_float(
            "average_frame_time_ms", fallback.average_frame_time_ms
        ),
        gpu_hourly_rate=_as_float("gpu_hourly_rate", fallback.gpu_hourly_rate),
        gpu_count=_as_int("gpu_count", fallback.gpu_count),
        render_hours=_as_float("render_hours", fallback.render_hours),
        render_farm_hourly_rate=_as_float(
            "render_farm_hourly_rate", fallback.render_farm_hourly_rate
        ),
        storage_gb=_as_float("storage_gb", fallback.storage_gb),
        storage_rate_per_gb=_as_float(
            "storage_rate_per_gb", fallback.storage_rate_per_gb
        ),
        data_egress_gb=_as_float("data_egress_gb", fallback.data_egress_gb),
        egress_rate_per_gb=_as_float("egress_rate_per_gb", fallback.egress_rate_per_gb),
        misc_costs=_as_float("misc_costs", fallback.misc_costs),
        currency=fallback.currency,
    )


def _safe_float(value: object, default: float, *, setting: str) -> float:
    """Parse *value* as a float, returning *default* when invalid."""

    if value is None:
        return default
    coerced = _coerce_float(value)
    if coerced is not None:
        return coerced
    LOGGER.warning(
        "Ignoring invalid %s override %r; using default %s", setting, value, default
    )
    return default


__all__ = [
    "DEFAULT_BASELINE_COST_INPUT",
    "DEFAULT_PNL_BASELINE_COST",
    "DEFAULT_SETTINGS_PATH",
    "DEFAULT_TARGET_ERROR_RATE",
    "SettingsLoadResult",
    "_coerce_cost_model_input",
    "_load_settings",
    "_safe_float",
]
