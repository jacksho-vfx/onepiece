"""Utilities for interacting with DCC applications.

This module intentionally keeps a very small public surface so that it can be
used in both the CLI application and by external tooling.  Only the features
needed by the tests are implemented which keeps the behaviour easy to reason
about.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import logging

from libraries.integrations.aws.s5_sync import s5_sync
from libraries.creative.dcc.maya.unreal_export_checker import (
    UnrealExportReport,
    validate_unreal_export,
)

from .models import (
    JSONValue,
    LinkStrategy,
    SupportedDCC,
    DCC_ASSET_REQUIREMENTS,
    DCCDependencyReport,
    DCCGPUStatus,
    DCCPluginStatus,
    DCCAssetStatus,
    DCC_GPU_REQUIREMENTS,
    DCC_PLUGIN_REQUIREMENTS,
)
from .packaging import (
    _prepare_package_contents,
    _profile_s5cmd_overrides,
    _write_package_manifest,
)
from .validation import (
    _format_unreal_export_error,
    _gather_maya_validation_kwargs,
)

__all__ = [
    "SupportedDCC",
    "LinkStrategy",
    "PublishSceneResult",
    "open_scene",
    "publish_scene",
    "verify_dcc_dependencies",
]


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishSceneResult:
    """Result of packaging and mirroring a DCC scene."""

    package_dir: Path
    destination: str


def _build_launch_command(dcc: SupportedDCC, path: Path) -> list[str]:
    """Return the command list that should be executed for *dcc*.

    ``Path`` objects are normalised to strings so that callers do not need to
    worry about the type of path they supply.  Only very small DCC specific
    differences are required so a plain lookup is sufficient.
    """

    if not isinstance(dcc, SupportedDCC):  # pragma: no cover - defensive.
        raise TypeError("dcc must be an instance of SupportedDCC")

    return [dcc.command, str(path)]


def open_scene(dcc: SupportedDCC, file_path: Path | str) -> None:
    """Open *file_path* inside the supplied *dcc*.

    The implementation purposefully avoids enforcing the existence of the file –
    doing so would complicate testing and prevent dry-run style usage.  The
    selected DCC determines the command that is executed and ``subprocess.run``
    is used with ``check=True`` so any failure from the external command is
    surfaced as a ``CalledProcessError``.
    """

    path = Path(file_path)
    command = _build_launch_command(dcc, path)
    subprocess.run(command, check=True)


def _plugins_from_env(dcc: SupportedDCC, env: Mapping[str, str]) -> frozenset[str]:
    """Return available plugins for ``dcc`` based on environment variables."""

    key = f"ONEPIECE_{dcc.name}_PLUGINS"
    raw_plugins = env.get(key, "")
    plugins = {item.strip().lower() for item in raw_plugins.split(",") if item.strip()}
    return frozenset(plugins)


def _gpu_from_env(dcc: SupportedDCC, env: Mapping[str, str]) -> str | None:
    """Return the GPU description sourced from the environment when available."""

    dcc_key = f"ONEPIECE_{dcc.name}_GPU"
    if gpu := env.get(dcc_key):
        return gpu
    return env.get("ONEPIECE_GPU")


def _normalise_required_plugins(
    dcc: SupportedDCC, extra_plugins: Iterable[str] | None
) -> frozenset[str]:
    """Return the set of plugins that must be available for ``dcc``."""

    baseline = {plugin.lower() for plugin in DCC_PLUGIN_REQUIREMENTS.get(dcc, ())}
    if extra_plugins:
        baseline.update(
            plugin.strip().lower() for plugin in extra_plugins if plugin.strip()
        )
    return frozenset(sorted(baseline))


def _normalise_required_assets(
    dcc: SupportedDCC, required_assets: Sequence[str] | None
) -> tuple[str, ...]:
    """Return the relative asset paths required for ``dcc``."""

    if required_assets is not None:
        entries = tuple(sorted(str(Path(asset)) for asset in required_assets))
    else:
        entries = DCC_ASSET_REQUIREMENTS.get(dcc, ())
    return entries


def _resolve_asset_status(package_root: Path, assets: Sequence[str]) -> DCCAssetStatus:
    """Return the asset status for ``package_root`` given ``assets``."""

    required_paths = tuple(package_root / asset for asset in assets)
    present: list[Path] = []
    missing: list[Path] = []
    for path in required_paths:
        if path.exists():
            present.append(path)
        else:
            missing.append(path)
    return DCCAssetStatus(
        required=tuple(required_paths),
        present=tuple(present),
        missing=tuple(missing),
    )


def verify_dcc_dependencies(
    dcc: SupportedDCC,
    package_root: Path,
    *,
    plugin_inventory: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
    required_plugins: Iterable[str] | None = None,
    required_assets: Sequence[str] | None = None,
    gpu_description: str | None = None,
    required_gpu: str | None = None,
) -> DCCDependencyReport:
    """Return a dependency report validating packaged assets, plugins, and GPU."""

    env_mapping = dict(env or os.environ)
    if plugin_inventory is None:
        available_plugins = _plugins_from_env(dcc, env_mapping)
    else:
        available_plugins = frozenset(
            plugin.strip().lower() for plugin in plugin_inventory if plugin.strip()
        )

    plugins_required = _normalise_required_plugins(dcc, required_plugins)
    missing_plugins = frozenset(sorted(plugins_required - available_plugins))
    plugins_status = DCCPluginStatus(
        required=plugins_required,
        available=available_plugins,
        missing=missing_plugins,
    )

    asset_entries = _normalise_required_assets(dcc, required_assets)
    assets_status = _resolve_asset_status(package_root, asset_entries)

    gpu_requirement = (
        required_gpu if required_gpu is not None else DCC_GPU_REQUIREMENTS.get(dcc)
    )
    detected_gpu: str | None
    if gpu_description is not None:
        detected_gpu = gpu_description
    else:
        detected_gpu = _gpu_from_env(dcc, env_mapping)

    meets_gpu_requirement = True
    if gpu_requirement:
        if detected_gpu:
            meets_gpu_requirement = gpu_requirement.lower() in detected_gpu.lower()
        else:
            meets_gpu_requirement = False

    gpu_status: DCCGPUStatus | None = None
    if gpu_requirement or detected_gpu is not None:
        gpu_status = DCCGPUStatus(
            required=gpu_requirement,
            detected=detected_gpu,
            meets_requirement=meets_gpu_requirement,
        )

    return DCCDependencyReport(
        dcc=dcc,
        plugins=plugins_status,
        assets=assets_status,
        gpu=gpu_status,
    )


def _resolve_s5cmd_settings(
    concurrency: int | None,
    part_size: str | None,
) -> tuple[int | None, str | None]:
    """Return the s5cmd overrides honouring CLI and profile sources."""

    profile_concurrency, profile_part_size = _profile_s5cmd_overrides()

    resolved_concurrency = (
        concurrency if concurrency is not None else profile_concurrency
    )
    if resolved_concurrency is not None and resolved_concurrency <= 0:
        raise ValueError("s5_concurrency must be greater than zero")

    resolved_part_size = part_size if part_size is not None else profile_part_size
    if resolved_part_size is not None and not str(resolved_part_size).strip():
        raise ValueError("s5_part_size must be a non-empty string when provided")

    return resolved_concurrency, resolved_part_size


def _select_thumbnail(candidates: Iterable[Path]) -> Path | None:
    """Return the first plausible thumbnail candidate from ``candidates``."""

    thumbnail_exts = {".jpg", ".jpeg", ".png", ".exr", ".tif", ".tiff"}
    for candidate in candidates:
        if candidate.suffix.lower() in thumbnail_exts:
            return candidate
    return None


def _format_dependency_error(report: DCCDependencyReport, package_dir: Path) -> str:
    """Return a human friendly error message for ``report``."""

    problems: list[str] = []

    if report.plugins.missing:
        missing_plugins = ", ".join(sorted(report.plugins.missing))
        problems.append(f"missing plugins: {missing_plugins}")

    if report.assets.missing:
        missing_assets: list[str] = []
        for path in report.assets.missing:
            try:
                missing_assets.append(str(path.relative_to(package_dir)))
            except ValueError:  # pragma: no cover - defensive fallback
                missing_assets.append(str(path))
        problems.append(f"missing assets: {', '.join(missing_assets)}")

    if report.gpu and not report.gpu.meets_requirement:
        if report.gpu.required:
            requirement = report.gpu.required
        else:  # pragma: no cover - defensive fallback
            requirement = "compatible GPU"
        detected = report.gpu.detected or "not detected"
        problems.append(
            f"GPU requirement not met (required {requirement}; detected {detected})"
        )

    if not problems:
        problems.append("unresolved dependency issues")

    return (
        "Dependency validation failed; resolve the following before publishing: "
        + "; ".join(problems)
    )


def _write_metadata_and_thumbnails(
    package_dir: Path,
    metadata: Mapping[str, JSONValue],
    previews_files: Sequence[Path],
    renders_files: Sequence[Path],
) -> tuple[Path, Path | None]:
    """Serialise ``metadata`` and create a thumbnail when possible."""

    metadata_path = package_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True))

    thumbnail_candidate = _select_thumbnail(previews_files or renders_files)
    thumbnail_path: Path | None = None
    if thumbnail_candidate:
        thumbs_dir = package_dir / "thumbnails"
        thumbs_dir.mkdir(exist_ok=True)
        thumbnail_path = thumbs_dir / thumbnail_candidate.name
        shutil.copy2(thumbnail_candidate, thumbnail_path)

    return metadata_path, thumbnail_path


def _assemble_dependency_report(
    dcc: SupportedDCC,
    package_dir: Path,
    *,
    dependency_callback: Callable[[DCCDependencyReport], None] | None = None,
    plugin_inventory: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
    required_plugins: Iterable[str] | None = None,
    required_assets: Sequence[str] | None = None,
    gpu_description: str | None = None,
    required_gpu: str | None = None,
) -> DCCDependencyReport:
    """Create and optionally dispatch a dependency report for the package."""

    report = verify_dcc_dependencies(
        dcc,
        package_dir,
        plugin_inventory=plugin_inventory,
        env=env,
        required_plugins=required_plugins,
        required_assets=required_assets,
        gpu_description=gpu_description,
        required_gpu=required_gpu,
    )

    if dependency_callback is not None:
        dependency_callback(report)

    return report


def _sync_package_to_s3(
    package_dir: Path,
    *,
    dcc: SupportedDCC,
    scene_name: str,
    bucket: str,
    show_code: str,
    show_type: Literal["vfx", "prod"],
    dry_run: bool,
    profile: str | None,
    direct_s3_path: str | None,
    concurrency: int | None,
    part_size: str | None,
) -> str:
    """Synchronise the packaged scene to S3 and return the destination path."""

    if direct_s3_path:
        destination_path = direct_s3_path
    else:
        show_type_segment = show_type.strip("/") or show_type
        show_code_segment = show_code.strip("/") or show_code
        destination_path = (
            f"s3://{bucket}/{show_type_segment}/{show_code_segment}/{scene_name}"
        )

    log.info(
        "publish_scene_packaged dcc=%s package=%s bucket=%s show_code=%s show_type=%s destination=%s",
        dcc.value,
        str(package_dir),
        bucket,
        show_code,
        show_type,
        destination_path,
        extra={
            "s5cmd_concurrency": concurrency if concurrency is not None else "default",
            "s5cmd_part_size": part_size,
        },
    )

    s5_sync(
        source=package_dir,
        destination=destination_path,
        dry_run=dry_run,
        include=None,
        exclude=None,
        profile=profile,
        concurrency=concurrency,
        part_size=part_size,
    )

    return destination_path


def publish_scene(
    dcc: SupportedDCC,
    scene_name: str,
    renders: Path,
    previews: Path,
    otio: Path,
    metadata: dict[str, JSONValue],
    destination: Path,
    bucket: str,
    show_code: str,
    show_type: Literal["vfx", "prod"] = "vfx",
    *,
    link_strategy: LinkStrategy = "copy",
    force_package: bool = False,
    dry_run: bool = False,
    profile: str | None = None,
    direct_s3_path: str | None = None,
    s5_concurrency: int | None = None,
    s5_part_size: str | None = None,
    dependency_callback: Callable[[DCCDependencyReport], None] | None = None,
    plugin_inventory: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
    required_plugins: Iterable[str] | None = None,
    required_assets: Sequence[str] | None = None,
    gpu_description: str | None = None,
    required_gpu: str | None = None,
    maya_validation_callback: Callable[[UnrealExportReport], None] | None = None,
) -> PublishSceneResult:
    """Package a scene's outputs locally and mirror them to S3.

    Returns a :class:`PublishSceneResult` containing the path to the packaged
    directory on disk as well as the destination used for the mirrored upload.
    When provided, ``gpu_description`` records the detected GPU capability in the
    dependency report while ``required_gpu`` allows overriding the default
    :data:`DCC_GPU_REQUIREMENTS` entry for ad-hoc validations.
    ``s5_concurrency`` and ``s5_part_size`` allow overriding the corresponding
    :command:`s5cmd` flags either directly or via OnePiece profile configuration.
    When omitted, :command:`s5cmd` defaults are used.
    """

    package_dir, renders_files, previews_files, package_manifest = (
        _prepare_package_contents(
            scene_name,
            renders,
            previews,
            otio,
            destination,
            link_strategy=link_strategy,
            force_package=force_package,
        )
    )

    _write_metadata_and_thumbnails(
        package_dir,
        metadata,
        previews_files,
        renders_files,
    )

    if dcc is SupportedDCC.MAYA:
        validation_kwargs = _gather_maya_validation_kwargs(package_dir)
        if validation_kwargs is not None:
            report = validate_unreal_export(**validation_kwargs)
            if maya_validation_callback is not None:
                maya_validation_callback(report)
            if not report.is_valid:
                message = _format_unreal_export_error(report)
                log.error(
                    "publish_scene_maya_unreal_validation_failed",
                    extra={"package": str(package_dir), "details": message},
                )
                raise RuntimeError(message)
        else:
            log.debug(
                "Maya validation skipped; insufficient data",
                extra={"package": str(package_dir)},
            )

    report = _assemble_dependency_report(
        dcc,
        package_dir,
        dependency_callback=dependency_callback,
        plugin_inventory=plugin_inventory,
        env=env,
        required_plugins=required_plugins,
        required_assets=required_assets,
        gpu_description=gpu_description,
        required_gpu=required_gpu,
    )

    if not report.is_valid:
        message = _format_dependency_error(report, package_dir)
        log.error(
            "publish_scene_dependency_failure dcc=%s package=%s message=%s",
            dcc.value,
            str(package_dir),
            message,
        )
        raise RuntimeError(message)

    resolved_concurrency, resolved_part_size = _resolve_s5cmd_settings(
        s5_concurrency,
        s5_part_size,
    )

    destination_path = _sync_package_to_s3(
        package_dir,
        dcc=dcc,
        scene_name=scene_name,
        bucket=bucket,
        show_code=show_code,
        show_type=show_type,
        dry_run=dry_run,
        profile=profile,
        direct_s3_path=direct_s3_path,
        concurrency=resolved_concurrency,
        part_size=resolved_part_size,
    )

    _write_package_manifest(package_dir, package_manifest)

    return PublishSceneResult(package_dir=package_dir, destination=destination_path)
