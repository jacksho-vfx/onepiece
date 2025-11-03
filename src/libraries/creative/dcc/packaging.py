"""Helpers for assembling and maintaining packaged DCC scene outputs."""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import shutil
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePath
from typing import Any

from .models import LinkStrategy

log = logging.getLogger(__name__)


PackageManifest = dict[str, dict[str, Any]]

_COPY_WORKERS_ENV = "ONEPIECE_DCC_COPY_WORKERS"
_S5CMD_CONCURRENCY_KEY = "s5cmd_concurrency"
_S5CMD_PART_SIZE_KEY = "s5cmd_part_size"
_INVALID_SCENE_NAME_MESSAGE = (
    "scene_name must be a simple name without path separators or traversal components"
)


@functools.lru_cache(maxsize=1)
def _profile_copy_worker_override() -> int | None:
    """Return the copy worker override sourced from OnePiece profiles."""

    try:
        from apps.onepiece.config import load_profile
        from apps.onepiece.utils.errors import OnePieceConfigError
    except ModuleNotFoundError:  # pragma: no cover - optional dependency for tests.
        return None

    try:
        profile = load_profile()
    except OnePieceConfigError as exc:  # pragma: no cover - surfaced via CLI.
        log.debug(
            "publish_scene_profile_resolution_failed",
            extra={"error": str(exc)},
        )
        return None

    dcc_settings = profile.data.get("dcc")
    if not isinstance(dcc_settings, Mapping):
        return None

    value = dcc_settings.get("copy_workers")
    if isinstance(value, int) and value > 0:
        return value
    if value is not None:
        log.warning(
            "publish_scene_invalid_profile_copy_workers",
            extra={"value": value, "profile": profile.name},
        )
    return None


@functools.lru_cache(maxsize=1)
def _profile_s5cmd_overrides() -> tuple[int | None, str | None]:
    """Return (concurrency, part-size) overrides sourced from profiles."""

    try:
        from apps.onepiece.config import load_profile
        from apps.onepiece.utils.errors import OnePieceConfigError
    except ModuleNotFoundError:  # pragma: no cover - optional dependency for tests.
        return (None, None)

    try:
        profile = load_profile()
    except OnePieceConfigError as exc:  # pragma: no cover - surfaced via CLI.
        log.debug(
            "publish_scene_profile_resolution_failed",
            extra={"error": str(exc)},
        )
        return (None, None)

    dcc_settings = profile.data.get("dcc")
    if not isinstance(dcc_settings, Mapping):
        return (None, None)

    concurrency_value = dcc_settings.get(_S5CMD_CONCURRENCY_KEY)
    part_size_value = dcc_settings.get(_S5CMD_PART_SIZE_KEY)

    resolved_concurrency: int | None = None
    if isinstance(concurrency_value, int):
        if concurrency_value > 0:
            resolved_concurrency = concurrency_value
        else:
            log.warning(
                "publish_scene_invalid_profile_s5cmd_concurrency",
                extra={"value": concurrency_value, "profile": profile.name},
            )
    elif concurrency_value is not None:
        log.warning(
            "publish_scene_invalid_profile_s5cmd_concurrency",
            extra={"value": concurrency_value, "profile": profile.name},
        )

    resolved_part_size: str | None = None
    if isinstance(part_size_value, str):
        if part_size_value.strip():
            resolved_part_size = part_size_value
        else:
            log.warning(
                "publish_scene_invalid_profile_s5cmd_part_size",
                extra={"value": part_size_value, "profile": profile.name},
            )
    elif part_size_value is not None:
        log.warning(
            "publish_scene_invalid_profile_s5cmd_part_size",
            extra={"value": part_size_value, "profile": profile.name},
        )

    return resolved_concurrency, resolved_part_size


def _resolve_copy_workers() -> int:
    """Return the number of worker threads used for packaging copies."""

    env_override = os.environ.get(_COPY_WORKERS_ENV)
    if env_override:
        try:
            value = int(env_override)
        except ValueError:
            log.warning(
                "publish_scene_invalid_env_copy_workers",
                extra={"value": env_override},
            )
        else:
            if value > 0:
                return value
            log.warning(
                "publish_scene_invalid_env_copy_workers",
                extra={"value": env_override},
            )

    profile_override = _profile_copy_worker_override()
    if profile_override is not None:
        return profile_override

    cpu_count = os.cpu_count() or 4
    return max(1, min(32, cpu_count))


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


def _manifest_path(package_dir: Path) -> Path:
    return package_dir / ".onepiece-package.json"


def _load_package_manifest(package_dir: Path) -> PackageManifest:
    """Return the stored package manifest for ``package_dir`` when available."""

    path = _manifest_path(package_dir)
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        log.warning(
            "publish_scene_manifest_unreadable",
            extra={"package": str(package_dir), "error": str(exc)},
        )
        return {}

    files = payload.get("files")
    if not isinstance(files, Mapping):
        return {}

    manifest: PackageManifest = {}
    for relative, entry in files.items():
        if not isinstance(relative, str) or not isinstance(entry, Mapping):
            continue
        size = entry.get("size")
        if not isinstance(size, int):
            continue
        manifest_entry: dict[str, Any] = {"size": size}
        checksum = entry.get("checksum")
        if isinstance(checksum, str):
            manifest_entry["checksum"] = checksum
        manifest[relative] = manifest_entry
    return manifest


def _write_package_manifest(package_dir: Path, manifest: PackageManifest) -> None:
    """Persist ``manifest`` for ``package_dir``."""

    path = _manifest_path(package_dir)
    serialisable = {key: value for key, value in sorted(manifest.items())}
    payload = {"files": serialisable}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _prune_stale_package_files(
    package_dir: Path,
    previous_manifest: PackageManifest,
    manifest: PackageManifest,
) -> None:
    """Remove files that disappeared between manifest revisions."""

    stale_keys = set(previous_manifest) - set(manifest)
    for key in stale_keys:
        target = package_dir / key
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        except FileNotFoundError:
            continue

        parent = target.parent
        while parent != package_dir:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _calculate_checksum(path: Path) -> str:
    """Return a stable checksum for ``path`` contents."""

    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _copy_output(
    src: Path,
    dst: Path,
    *,
    treat_dst_as_dir: bool = False,
    link_strategy: LinkStrategy = "copy",
    package_dir: Path | None = None,
    previous_manifest: PackageManifest | None = None,
    new_manifest: PackageManifest | None = None,
    force_package: bool = False,
) -> list[Path]:
    """Copy ``src`` to ``dst`` and return the created files."""

    requested_strategy = link_strategy
    downgrade_logged = False
    downgrade_lock = threading.Lock()
    manifest_lock = threading.Lock()

    def _log_downgrade(error: OSError, target_path: Path) -> None:
        nonlocal downgrade_logged
        with downgrade_lock:
            if downgrade_logged:
                return
            log.warning(
                "publish_scene_link_downgraded",
                extra={
                    "requested_strategy": requested_strategy,
                    "source": str(src),
                    "target": str(target_path),
                    "error": str(error),
                },
            )
            downgrade_logged = True

    def _manifest_key(path: Path) -> str | None:
        if package_dir is None:
            return None
        try:
            return str(path.relative_to(package_dir))
        except ValueError:
            return None

    def _previous_entry(key: str | None) -> dict[str, Any] | None:
        if key is None or previous_manifest is None:
            return None
        return previous_manifest.get(key)

    def _record_entry(key: str | None, entry: dict[str, Any]) -> None:
        if key is None or new_manifest is None:
            return
        with manifest_lock:
            new_manifest[key] = entry

    def _calculate_entry(source: Path, entry: dict[str, Any] | None) -> dict[str, Any]:
        checksum_required = bool(entry and entry.get("checksum"))
        result: dict[str, Any] = {"size": source.stat().st_size}
        if checksum_required:
            result["checksum"] = _calculate_checksum(source)
        return result

    def _should_skip(
        source: Path,
        target_path: Path,
        key: str | None,
    ) -> tuple[bool, dict[str, Any] | None]:
        if force_package or previous_manifest is None or key is None:
            return False, None
        entry = previous_manifest.get(key)
        if entry is None:
            return False, None
        if entry.get("size") != source.stat().st_size:
            return False, None
        checksum = entry.get("checksum")
        if checksum:
            if _calculate_checksum(source) != checksum:
                return False, None
        if not target_path.exists() and not target_path.is_symlink():
            return False, None
        return True, entry

    created_files: list[Path] = []
    if src.is_dir():
        if link_strategy == "symlink":
            if dst.exists():
                if dst.is_symlink() or not dst.is_dir():
                    dst.unlink()
                else:
                    shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                dst.symlink_to(src, target_is_directory=True)
                created_files = [p for p in dst.rglob("*") if p.is_file()]
            except OSError as exc:
                _log_downgrade(exc, dst)
                shutil.copytree(src, dst)
                created_files = [p for p in dst.rglob("*") if p.is_file()]

            for child in sorted(src.rglob("*")):
                if not child.is_file():
                    continue
                relative = child.relative_to(src)
                target_path = dst / relative
                key = _manifest_key(target_path)
                entry = _calculate_entry(child, _previous_entry(key))
                _record_entry(key, entry)
            return created_files

        if dst.exists() and (dst.is_symlink() or not dst.is_dir()):
            dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.mkdir(parents=True, exist_ok=True)

        effective_strategy: LinkStrategy = link_strategy
        strategy_lock = threading.Lock()
        created_entries: list[tuple[int, Path]] = []
        created_lock = threading.Lock()

        files_to_process: list[tuple[int, Path]] = []
        index = 0
        for child in sorted(src.rglob("*")):
            if child.is_dir():
                (dst / child.relative_to(src)).mkdir(parents=True, exist_ok=True)
                continue
            files_to_process.append((index, child))
            index += 1

        def _process_file(task: tuple[int, Path]) -> None:
            nonlocal effective_strategy
            file_index, child = task
            relative = child.relative_to(src)
            target_path = dst / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            key = _manifest_key(target_path)
            skip, existing_entry = _should_skip(child, target_path, key)
            if skip:
                if existing_entry is not None:
                    _record_entry(key, existing_entry)
                with created_lock:
                    created_entries.append((file_index, target_path))
                return

            if target_path.exists() or target_path.is_symlink():
                if target_path.is_dir() and not target_path.is_symlink():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()

            while True:
                with strategy_lock:
                    local_strategy = effective_strategy
                try:
                    if local_strategy == "copy":
                        shutil.copy2(child, target_path)
                    elif local_strategy == "hard":
                        os.link(child, target_path)
                    else:
                        os.symlink(child, target_path)
                    break
                except OSError as exc:
                    if local_strategy == "copy":
                        raise
                    _log_downgrade(exc, target_path)
                    with strategy_lock:
                        effective_strategy = "copy"

            entry = _calculate_entry(child, _previous_entry(key))
            if entry:
                _record_entry(key, entry)
            with created_lock:
                created_entries.append((file_index, target_path))

        worker_count = _resolve_copy_workers()
        if files_to_process and worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(_process_file, task) for task in files_to_process
                ]
                for future in futures:
                    future.result()
        else:
            for task in files_to_process:
                _process_file(task)

        created_files = [
            path for _, path in sorted(created_entries, key=lambda item: item[0])
        ]
        return created_files

    target = dst
    if treat_dst_as_dir or (dst.exists() and dst.is_dir()):
        dst.mkdir(parents=True, exist_ok=True)
        target = dst / src.name
    else:
        if dst.suffix == "":
            target = dst / src.name

    key = _manifest_key(target)
    skip, existing_entry = _should_skip(src, target, key)
    if not skip:
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()

        target.parent.mkdir(parents=True, exist_ok=True)
        effective_strategy = link_strategy
        while True:
            try:
                if effective_strategy == "copy":
                    shutil.copy2(src, target)
                elif effective_strategy == "hard":
                    os.link(src, target)
                else:
                    os.symlink(src, target)
                break
            except OSError as exc:
                if effective_strategy == "copy":
                    raise
                _log_downgrade(exc, target)
                effective_strategy = "copy"

        entry = _calculate_entry(src, _previous_entry(key))
    else:
        entry = existing_entry or {}

    if entry:
        _record_entry(key, entry)

    return [target]


def _prepare_package_contents(
    scene_name: str,
    renders: Path,
    previews: Path,
    otio: Path,
    destination: Path,
    *,
    link_strategy: LinkStrategy = "copy",
    force_package: bool = False,
) -> tuple[Path, list[Path], list[Path], PackageManifest]:
    """Create the package directory and populate it with scene outputs."""

    _validate_scene_name(scene_name)
    package_dir = destination / scene_name
    package_dir.mkdir(parents=True, exist_ok=True)

    stored_manifest = _load_package_manifest(package_dir)
    previous_manifest = {} if force_package else stored_manifest
    manifest: PackageManifest = {}

    renders_files = _copy_output(
        Path(renders),
        package_dir / "renders",
        treat_dst_as_dir=True,
        link_strategy=link_strategy,
        package_dir=package_dir,
        previous_manifest=previous_manifest,
        new_manifest=manifest,
        force_package=force_package,
    )
    previews_files = _copy_output(
        Path(previews),
        package_dir / "previews",
        treat_dst_as_dir=True,
        link_strategy=link_strategy,
        package_dir=package_dir,
        previous_manifest=previous_manifest,
        new_manifest=manifest,
        force_package=force_package,
    )
    _copy_output(
        Path(otio),
        package_dir / "otio",
        treat_dst_as_dir=True,
        link_strategy=link_strategy,
        package_dir=package_dir,
        previous_manifest=previous_manifest,
        new_manifest=manifest,
        force_package=force_package,
    )

    _prune_stale_package_files(package_dir, stored_manifest, manifest)

    return package_dir, renders_files, previews_files, manifest


__all__ = [
    "PackageManifest",
    "_profile_copy_worker_override",
    "_profile_s5cmd_overrides",
    "_resolve_copy_workers",
    "_validate_scene_name",
    "_load_package_manifest",
    "_write_package_manifest",
    "_prune_stale_package_files",
    "_copy_output",
    "_prepare_package_contents",
]
