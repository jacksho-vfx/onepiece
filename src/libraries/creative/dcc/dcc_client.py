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
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Literal, TypeAlias

import logging

from libraries.integrations.aws.s5_sync import s5_sync
from libraries.creative.dcc.maya.unreal_export_checker import (
    UnrealExportIssue,
    UnrealExportReport,
    validate_unreal_export,
)

__all__ = [
    "SupportedDCC",
    "open_scene",
    "publish_scene",
    "PublishSceneResult",
    "verify_dcc_dependencies",
    "DCCDependencyReport",
    "DCCPluginStatus",
    "DCCAssetStatus",
    "DCC_PLUGIN_REQUIREMENTS",
    "DCC_GPU_REQUIREMENTS",
    "DCC_ASSET_REQUIREMENTS",
]


log = logging.getLogger(__name__)


class SupportedDCC(Enum):
    """Enumeration of DCC applications that OnePiece knows how to launch."""

    NUKE = "Nuke"
    MAYA = "Maya"
    BLENDER = "blender"
    HOUDINI = "houdini"
    MAX = "3dsmax"

    @property
    def command(self) -> str:
        """Return the executable name associated with the DCC."""

        if self is SupportedDCC.MAYA:
            base_command = "maya"
            if os.name == "nt":
                return f"{base_command}.exe"
            return base_command

        return str(self.value)


DCC_PLUGIN_REQUIREMENTS: dict[SupportedDCC, frozenset[str]] = {
    SupportedDCC.NUKE: frozenset({"CaraVR", "OCIO"}),
    SupportedDCC.MAYA: frozenset({"mtoa", "bifrost"}),
    SupportedDCC.BLENDER: frozenset({"cycles"}),
    SupportedDCC.HOUDINI: frozenset({"karma"}),
    SupportedDCC.MAX: frozenset({"vray"}),
}


DCC_GPU_REQUIREMENTS: dict[SupportedDCC, str] = {
    SupportedDCC.NUKE: "OpenGL 4.1",
    SupportedDCC.MAYA: "DirectX 11",
    SupportedDCC.BLENDER: "OpenGL 4.3",
    SupportedDCC.HOUDINI: "Vulkan",
    SupportedDCC.MAX: "DirectX 12",
}


DCC_ASSET_REQUIREMENTS: dict[SupportedDCC, tuple[str, ...]] = {
    SupportedDCC.NUKE: ("toolsets/init.gizmo", "luts/show_lut.cube"),
    SupportedDCC.MAYA: ("modules/arnold.mod", "scripts/userSetup.mel"),
    SupportedDCC.BLENDER: ("config/startup.blend",),
    SupportedDCC.HOUDINI: ("packages/onepiece.json",),
    SupportedDCC.MAX: ("plugins/onepiece.dlx",),
}


@dataclass
class DCCPluginStatus:
    """Summary of plugin availability for a DCC."""

    required: frozenset[str]
    available: frozenset[str]
    missing: frozenset[str]


@dataclass
class DCCAssetStatus:
    """Summary of asset availability for a packaged scene."""

    required: tuple[Path, ...]
    present: tuple[Path, ...]
    missing: tuple[Path, ...]


@dataclass
class DCCDependencyReport:
    """Aggregate report describing dependency readiness for a DCC package."""

    dcc: SupportedDCC
    plugins: DCCPluginStatus
    assets: DCCAssetStatus

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when no plugin or asset requirements are missing."""

        return not self.plugins.missing and not self.assets.missing


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
) -> DCCDependencyReport:
    """Return a dependency report validating packaged assets and plugins."""

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

    return DCCDependencyReport(
        dcc=dcc,
        plugins=plugins_status,
        assets=assets_status,
    )


def _copy_output(src: Path, dst: Path, *, treat_dst_as_dir: bool = False) -> list[Path]:
    """Copy ``src`` to ``dst`` and return the created files."""

    if src.is_dir():
        if dst.exists():
            if dst.is_symlink() or not dst.is_dir():
                dst.unlink()
            else:
                shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return [p for p in dst.rglob("*") if p.is_file()]

    target = dst
    if treat_dst_as_dir or (dst.exists() and dst.is_dir()):
        target = dst / src.name
    else:
        if dst.suffix == "":
            target = dst / src.name

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return [target]


def _select_thumbnail(candidates: Iterable[Path]) -> Path | None:
    """Return the first plausible thumbnail candidate from ``candidates``."""

    thumbnail_exts = {".jpg", ".jpeg", ".png", ".exr", ".tif", ".tiff"}
    for candidate in candidates:
        if candidate.suffix.lower() in thumbnail_exts:
            return candidate
    return None


JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | dict[str, "JSONValue"] | list["JSONValue"]


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

    if not problems:
        problems.append("unresolved dependency issues")

    return (
        "Dependency validation failed; resolve the following before publishing: "
        + "; ".join(problems)
    )


def _prepare_package_contents(
    scene_name: str,
    renders: Path,
    previews: Path,
    otio: Path,
    destination: Path,
) -> tuple[Path, list[Path], list[Path]]:
    """Create the package directory and populate it with scene outputs."""

    _validate_scene_name(scene_name)
    package_dir = destination / scene_name
    package_dir.mkdir(parents=True, exist_ok=True)

    renders_files = _copy_output(
        Path(renders), package_dir / "renders", treat_dst_as_dir=True
    )
    previews_files = _copy_output(
        Path(previews), package_dir / "previews", treat_dst_as_dir=True
    )
    _copy_output(Path(otio), package_dir / "otio", treat_dst_as_dir=True)

    return package_dir, renders_files, previews_files


_INVALID_SCENE_NAME_MESSAGE = (
    "scene_name must be a simple name without path separators or traversal components"
)


def _validate_scene_name(scene_name: str) -> None:
    """Ensure ``scene_name`` cannot escape the destination directory."""

    if not scene_name or not scene_name.strip():
        raise ValueError(_INVALID_SCENE_NAME_MESSAGE)

    if scene_name in {".", ".."}:
        raise ValueError(_INVALID_SCENE_NAME_MESSAGE)

    candidate = PurePath(scene_name)
    if candidate.is_absolute():
        raise ValueError(_INVALID_SCENE_NAME_MESSAGE)

    separators = {os.sep, os.altsep, "/", "\\"}
    if any(sep and sep in scene_name for sep in separators):
        raise ValueError(_INVALID_SCENE_NAME_MESSAGE)

    if any(part in {".", ".."} for part in candidate.parts):
        raise ValueError(_INVALID_SCENE_NAME_MESSAGE)


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


def _load_package_metadata(package_dir: Path) -> Mapping[str, JSONValue] | None:
    """Return the metadata stored with the packaged scene when available."""

    metadata_path = package_dir / "metadata.json"
    try:
        data = json.loads(metadata_path.read_text())
    except FileNotFoundError:
        log.debug(
            "Maya validation skipped; metadata.json missing",
            extra={"package": str(package_dir)},
        )
        return None
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        log.warning(
            "Maya validation skipped; metadata.json unreadable",
            extra={"package": str(package_dir), "error": str(exc)},
        )
        return None

    if not isinstance(data, Mapping):
        log.warning(
            "Maya validation skipped; metadata.json not an object",
            extra={"package": str(package_dir)},
        )
        return None
    return data


def _normalise_sequence(value: Any) -> tuple[str, ...] | None:
    """Return *value* coerced to a tuple of strings when appropriate."""

    if isinstance(value, (str, bytes)):
        return (str(value),)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return None


def _load_skeleton_summary(
    skeleton_entry: JSONValue,
    package_dir: Path,
) -> tuple[str, tuple[str, ...]] | None:
    """Return skeleton root and joints extracted from ``skeleton_entry``."""

    skeleton_data: Mapping[str, JSONValue] | None
    if isinstance(skeleton_entry, Mapping):
        skeleton_data = skeleton_entry
    elif isinstance(skeleton_entry, str):
        skeleton_path = package_dir / skeleton_entry
        try:
            payload = json.loads(skeleton_path.read_text())
        except FileNotFoundError:
            log.warning(
                "Maya validation skipped; skeleton summary missing",
                extra={"package": str(package_dir), "path": skeleton_path.name},
            )
            return None
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            log.warning(
                "Maya validation skipped; skeleton summary unreadable",
                extra={
                    "package": str(package_dir),
                    "path": skeleton_path.name,
                    "error": str(exc),
                },
            )
            return None
        if not isinstance(payload, Mapping):
            log.warning(
                "Maya validation skipped; skeleton summary not an object",
                extra={"package": str(package_dir), "path": skeleton_path.name},
            )
            return None
        skeleton_data = payload
    else:
        return None

    root = skeleton_data.get("root")
    joints = skeleton_data.get("joints")
    if not isinstance(root, str):
        log.warning(
            "Maya validation skipped; skeleton root invalid",
            extra={"package": str(package_dir)},
        )
        return None

    normalised_joints = _normalise_sequence(joints)
    if not normalised_joints:
        log.warning(
            "Maya validation skipped; skeleton joints invalid",
            extra={"package": str(package_dir)},
        )
        return None

    return root, normalised_joints


def _gather_maya_validation_kwargs(package_dir: Path) -> dict[str, Any] | None:
    """Return keyword arguments for :func:`validate_unreal_export` when available."""

    metadata = _load_package_metadata(package_dir)
    if metadata is None:
        return None

    maya_data = metadata.get("maya")
    if not isinstance(maya_data, Mapping):
        return None

    unreal_data = maya_data.get("unreal_export")
    if not isinstance(unreal_data, Mapping):
        return None

    asset_name = unreal_data.get("asset_name")
    if not isinstance(asset_name, str):
        log.warning(
            "Maya validation skipped; asset name missing",
            extra={"package": str(package_dir)},
        )
        return None

    scale_value = unreal_data.get("scale")
    try:
        scale = float(scale_value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning(
            "Maya validation skipped; scale invalid",
            extra={"package": str(package_dir)},
        )
        return None

    skeleton_entry = unreal_data.get("skeleton_summary")
    skeleton = _load_skeleton_summary(skeleton_entry, package_dir)
    if skeleton is None:
        return None
    skeleton_root, joints = skeleton

    kwargs: dict[str, Any] = {
        "asset_name": asset_name,
        "scale": scale,
        "skeleton_root": skeleton_root,
        "joints": joints,
    }

    optional_fields = (
        "expected_scale",
        "scale_tolerance",
        "allowed_name_prefixes",
        "required_joints",
        "expected_root",
    )
    for field in optional_fields:
        if field not in unreal_data:
            continue
        value = unreal_data[field]
        if field in {"allowed_name_prefixes", "required_joints"}:
            normalised = _normalise_sequence(value)
            if normalised is not None:
                kwargs[field] = normalised
        else:
            kwargs[field] = value

    return kwargs


def _format_unreal_export_error(report: UnrealExportReport) -> str:
    """Return an error message describing ``report`` issues."""

    errors = [
        f"{issue.code}: {issue.message}"
        for issue in report.issues
        if isinstance(issue, UnrealExportIssue) and issue.severity == "error"
    ]
    if not errors:
        return "Maya Unreal export validation failed with unresolved issues."
    problems = "; ".join(errors)
    return f"Maya Unreal export validation failed; {problems}"


def _assemble_dependency_report(
    dcc: SupportedDCC,
    package_dir: Path,
    *,
    dependency_callback: Callable[[DCCDependencyReport], None] | None = None,
    plugin_inventory: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
    required_plugins: Iterable[str] | None = None,
    required_assets: Sequence[str] | None = None,
) -> DCCDependencyReport:
    """Create and optionally dispatch a dependency report for the package."""

    report = verify_dcc_dependencies(
        dcc,
        package_dir,
        plugin_inventory=plugin_inventory,
        env=env,
        required_plugins=required_plugins,
        required_assets=required_assets,
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
    )

    s5_sync(
        source=package_dir,
        destination=destination_path,
        dry_run=dry_run,
        include=None,
        exclude=None,
        profile=profile,
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
    dry_run: bool = False,
    profile: str | None = None,
    direct_s3_path: str | None = None,
    dependency_callback: Callable[[DCCDependencyReport], None] | None = None,
    plugin_inventory: Iterable[str] | None = None,
    env: Mapping[str, str] | None = None,
    required_plugins: Iterable[str] | None = None,
    required_assets: Sequence[str] | None = None,
    maya_validation_callback: Callable[[UnrealExportReport], None] | None = None,
) -> PublishSceneResult:
    """Package a scene's outputs locally and mirror them to S3.

    Returns a :class:`PublishSceneResult` containing the path to the packaged
    directory on disk as well as the destination used for the mirrored upload.
    """

    package_dir, renders_files, previews_files = _prepare_package_contents(
        scene_name,
        renders,
        previews,
        otio,
        destination,
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
    )

    return PublishSceneResult(package_dir=package_dir, destination=destination_path)
