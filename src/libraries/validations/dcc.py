"""Helpers for validating and inferring Digital Content Creation tools."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from libraries.dcc.dcc_client import (
    DCC_GPU_REQUIREMENTS,
    DCC_PLUGIN_REQUIREMENTS,
    SupportedDCC,
)

__all__ = [
    "SupportedDCC",
    "validate_dcc",
    "detect_dcc_from_file",
    "check_dcc_environment",
    "PluginValidation",
    "GPUValidation",
    "DCCEnvironmentReport",
]


_EXTENSION_MAP: dict[str, SupportedDCC] = {
    ".ma": SupportedDCC.MAYA,
    ".mb": SupportedDCC.MAYA,
    ".nk": SupportedDCC.NUKE,
    ".hip": SupportedDCC.HOUDINI,
    ".hipnc": SupportedDCC.HOUDINI,
    ".blend": SupportedDCC.BLENDER,
    ".max": SupportedDCC.MAX,
}


def validate_dcc(dcc_name: str | SupportedDCC) -> Any:
    """Return the :class:`SupportedDCC` matching ``dcc_name``.

    A :class:`SupportedDCC` instance is returned unchanged which keeps the helper
    ergonomic when the caller already performs validation elsewhere.
    """

    if isinstance(dcc_name, SupportedDCC):
        return dcc_name

    normalized = dcc_name.lower()
    for dcc in SupportedDCC:
        if dcc.value.lower() == normalized:
            return dcc
    supported = ", ".join(sorted(d.value for d in SupportedDCC))
    raise ValueError(f"Unsupported DCC: {dcc_name}. Supported: {supported}")


def detect_dcc_from_file(file_path: str | Path) -> Any:
    """Infer the appropriate :class:`SupportedDCC` from ``file_path``."""

    suffix = Path(file_path).suffix.lower()
    try:
        return _EXTENSION_MAP[suffix]
    except KeyError as exc:
        supported = ", ".join(sorted(_EXTENSION_MAP))
        msg = (
            f"Cannot detect DCC from file extension '{suffix}' (supported: {supported})"
        )
        raise ValueError(msg) from exc


@dataclass
class PluginValidation:
    """Represents plugin availability results for a DCC environment."""

    required: frozenset[str]
    available: frozenset[str]
    missing: frozenset[str]

    @property
    def is_satisfied(self) -> bool:
        """Return ``True`` when all required plugins are available."""

        return not self.missing


@dataclass
class GPUValidation:
    """Represents GPU capability checks for a DCC environment."""

    required: str | None
    detected: str | None
    meets_requirement: bool

    @property
    def is_detected(self) -> bool:
        """Return ``True`` when a GPU description was detected."""

        return self.detected is not None


@dataclass
class DCCEnvironmentReport:
    """Combined environment verification report for a DCC."""

    dcc: SupportedDCC
    installed: bool
    executable: str | None
    plugins: PluginValidation
    gpu: GPUValidation


def _plugins_from_env(dcc: SupportedDCC, env: Mapping[str, str]) -> frozenset[str]:
    """Return detected plugins from ``env`` for ``dcc``."""

    key = f"ONEPIECE_{dcc.name}_PLUGINS"
    raw_plugins = env.get(key, "")
    plugins = {part.strip() for part in raw_plugins.split(",") if part.strip()}
    return frozenset(sorted(plugins))


def _detect_executable(
    dcc: SupportedDCC, env: Mapping[str, str]
) -> tuple[bool, str | None]:
    """Return whether the DCC executable is available and its resolved path."""

    path_env = env.get("PATH")
    executable = shutil.which(dcc.command, path=path_env)
    return executable is not None, executable


def _gpu_from_env(dcc: SupportedDCC, env: Mapping[str, str]) -> str | None:
    """Return GPU description from environment variables."""

    dcc_key = f"ONEPIECE_{dcc.name}_GPU"
    if gpu := env.get(dcc_key):
        return gpu
    return env.get("ONEPIECE_GPU")


def check_dcc_environment(
    dcc: SupportedDCC,
    *,
    env: Mapping[str, str] | None = None,
    plugin_inventory: Mapping[SupportedDCC, frozenset[str]] | None = None,
    gpu_info: Mapping[SupportedDCC, str | None] | None = None,
) -> DCCEnvironmentReport:
    """Return an environment report validating a DCC installation."""

    env_mapping: Mapping[str, str] = env or os.environ

    installed, executable = _detect_executable(dcc, env_mapping)

    if plugin_inventory is not None:
        available_plugins = frozenset(sorted(plugin_inventory.get(dcc, frozenset())))
    else:
        available_plugins = _plugins_from_env(dcc, env_mapping)
    required_plugins = frozenset(sorted(DCC_PLUGIN_REQUIREMENTS.get(dcc, ())))
    missing_plugins = frozenset(sorted(required_plugins - available_plugins))
    plugin_result = PluginValidation(
        required=required_plugins,
        available=available_plugins,
        missing=missing_plugins,
    )

    required_gpu = DCC_GPU_REQUIREMENTS.get(dcc)
    if gpu_info is not None:
        detected_gpu = gpu_info.get(dcc)
    else:
        detected_gpu = _gpu_from_env(dcc, env_mapping)

    meets_requirement = True
    if required_gpu:
        if detected_gpu:
            meets_requirement = required_gpu.lower() in detected_gpu.lower()
        else:
            meets_requirement = False

    gpu_result = GPUValidation(
        required=required_gpu,
        detected=detected_gpu,
        meets_requirement=meets_requirement,
    )

    return DCCEnvironmentReport(
        dcc=dcc,
        installed=installed,
        executable=executable,
        plugins=plugin_result,
        gpu=gpu_result,
    )
