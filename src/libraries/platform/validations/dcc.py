"""Helpers for validating and inferring Digital Content Creation tools."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from libraries.creative.dcc.dcc_client import (
    DCC_ASSET_REQUIREMENTS,
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
    ".hiplc": SupportedDCC.HOUDINI,
    ".hipnc": SupportedDCC.HOUDINI,
    ".blend": SupportedDCC.BLENDER,
    ".max": SupportedDCC.MAX,
    ".vrscene": SupportedDCC.VRAY,
    ".c4d": SupportedDCC.CINEMA4D,
}


_DCC_ALIASES: dict[str, SupportedDCC] = {
    "3dsmax": SupportedDCC.MAX,
    "max": SupportedDCC.MAX,
    "c4d": SupportedDCC.CINEMA4D,
}

_CANONICAL_DCC_NAMES: dict[str, SupportedDCC] = {
    dcc.value.lower(): dcc for dcc in SupportedDCC
}

_SUPPORTED_DCC_LOOKUP: dict[str, SupportedDCC] = {
    **_CANONICAL_DCC_NAMES,
    **_DCC_ALIASES,
}


def validate_dcc(dcc_name: str | SupportedDCC) -> Any:
    """Return the :class:`SupportedDCC` matching ``dcc_name``.

    A :class:`SupportedDCC` instance is returned unchanged which keeps the helper
    ergonomic when the caller already performs validation elsewhere.
    """

    if isinstance(dcc_name, SupportedDCC):
        return dcc_name

    normalized = dcc_name.lower()
    try:
        return _SUPPORTED_DCC_LOOKUP[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(_SUPPORTED_DCC_LOOKUP))
        raise ValueError(
            f"Unsupported DCC: {dcc_name}. Supported: {supported}"
        ) from exc


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
    plugins = {part.strip().lower() for part in raw_plugins.split(",") if part.strip()}
    return frozenset(sorted(plugins))


def _detect_executable(
    dcc: SupportedDCC, env: Mapping[str, str]
) -> tuple[bool, str | None]:
    """Return whether the DCC executable is available and its resolved path."""

    path_env = env.get("PATH", "")
    executable_name = dcc.resolve_command(dict(env))
    executable = shutil.which(executable_name, path=path_env)
    return executable is not None, executable


def _gpu_from_env(dcc: SupportedDCC, env: Mapping[str, str]) -> str | None:
    """Return GPU description from environment variables."""

    dcc_key = f"ONEPIECE_{dcc.name}_GPU"
    if gpu := env.get(dcc_key):
        return gpu
    return env.get("ONEPIECE_GPU")


def _houdini_paths_from_hconfig(hconfig_output: str) -> frozenset[Path]:
    """Return HOUDINI_PATH entries parsed from ``hconfig -ap`` output."""

    paths: set[Path] = set()
    for line in hconfig_output.splitlines():
        if not line.lstrip().startswith("HOUDINI_PATH"):
            continue

        _, _, value = line.partition("=")
        if not value:
            continue

        value = value.strip().strip('"').strip("'")
        for entry in value.split(os.pathsep):
            normalized = entry.strip()
            if not normalized or normalized == "&":
                continue
            paths.add(Path(normalized))

    return frozenset(sorted(paths))


def _houdini_package_roots(env: Mapping[str, str]) -> frozenset[Path]:
    """Return Houdini package roots derived from environment and hconfig output."""

    roots: set[Path] = set()

    if raw_path := env.get("HOUDINI_PATH"):
        parts = [
            segment
            for segment in raw_path.split(os.pathsep)
            if segment and segment != "&"
        ]
        roots.update(Path(entry) for entry in parts)

    hconfig_output = env.get("HOUDINI_HCONFIG") or env.get("HCONFIG_AP")
    if hconfig_output:
        roots.update(_houdini_paths_from_hconfig(hconfig_output))

    return frozenset(sorted(roots))


def _houdini_available_assets(
    package_roots: frozenset[Path], required_assets: frozenset[str]
) -> frozenset[str]:
    """Return Houdini assets that exist under the supplied package roots."""

    available: set[str] = set()
    for asset in required_assets:
        asset_path = Path(asset)
        for root in package_roots:
            candidate = root / asset_path
            if candidate.exists():
                available.add(asset)
                break
    return frozenset(sorted(available))


def _houdini_has_karma(package_roots: frozenset[Path], env: Mapping[str, str]) -> bool:
    """Return ``True`` when Karma is detected via binaries or env hints."""

    candidates = []
    if hfs_root := env.get("HFS"):
        candidates.append(Path(hfs_root) / "bin" / "karma")

    candidates.extend(root / "bin" / "karma" for root in package_roots)

    if karma_path := env.get("KARMA_PATH"):
        candidates.append(Path(karma_path))

    return any(path.exists() for path in candidates)


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
        available_plugins = frozenset(
            sorted(plugin.lower() for plugin in plugin_inventory.get(dcc, frozenset()))
        )
    else:
        available_plugins = _plugins_from_env(dcc, env_mapping)

    required_plugins = frozenset(
        sorted(plugin.lower() for plugin in DCC_PLUGIN_REQUIREMENTS.get(dcc, ()))
    )

    if dcc is SupportedDCC.HOUDINI:
        required_assets = frozenset(
            sorted(asset.lower() for asset in DCC_ASSET_REQUIREMENTS.get(dcc, ()))
        )

        package_roots = _houdini_package_roots(env_mapping)
        available_assets = _houdini_available_assets(package_roots, required_assets)

        available_plugins = frozenset(sorted(available_plugins | available_assets))
        required_plugins = frozenset(sorted(required_plugins | required_assets))

        if _houdini_has_karma(package_roots, env_mapping):
            available_plugins = frozenset(sorted(available_plugins | {"karma"}))

        missing_plugins = frozenset(
            sorted(
                (required_plugins - available_plugins)
                | (required_assets - available_assets)
            )
        )
    else:
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
