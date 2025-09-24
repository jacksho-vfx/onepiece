"""Compatibility wrapper around Ruff's CLI.

The shim reintroduces support for running ``ruff`` without an explicit
subcommand, restoring the legacy ``ruff <paths>`` behaviour that was removed in
Ruff 0.5. The wrapper delegates to the official Ruff binary, installing it into
``~/.cache/onepiece`` on demand so it works regardless of the version bundled
with the current Python environment.
"""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable, List, Sequence

CACHE_ROOT = Path(
    os.environ.get("ONEPIECE_RUFF_CACHE", Path.home() / ".cache" / "onepiece" / "ruff")
)
KNOWN_SUBCOMMANDS = {
    "check",
    "rule",
    "config",
    "linter",
    "clean",
    "format",
    "generate-shell-completion",
    "help",
}


class RuffShimError(RuntimeError):
    """Raised when the shim cannot locate a usable Ruff binary."""


def _installed_version() -> str:
    try:
        return importlib.metadata.version("ruff")
    except (
        importlib.metadata.PackageNotFoundError
    ) as exc:  # pragma: no cover - defensive
        raise RuffShimError(
            "Ruff is not installed. Install it via 'pip install ruff' or the project's dev dependencies."
        ) from exc


def _ensure_binary(version: str) -> Path:
    target_dir = CACHE_ROOT / version
    binary = target_dir / "bin" / "ruff"
    if binary.exists():
        return binary

    target_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            f"ruff=={version}",
            "--target",
            str(target_dir),
        ],
        env=env,
    )
    if os.name == "nt":  # pragma: no cover - Windows specific
        binary.chmod(binary.stat().st_mode | 0o111)
    return binary


def _discover_subcommands(binary: Path) -> set[str]:
    try:
        help_output = subprocess.check_output([str(binary), "--help"], text=True)
    except subprocess.CalledProcessError:
        return set(KNOWN_SUBCOMMANDS)

    commands: set[str] = set()
    capture = False
    for line in help_output.splitlines():
        stripped = line.strip()
        if not stripped:
            if capture:
                break
            continue
        if stripped == "Commands:":
            capture = True
            continue
        if capture:
            commands.add(stripped.split()[0])
    return commands or set(KNOWN_SUBCOMMANDS)


def _needs_check_subcommand(args: Sequence[str], commands: set[str]) -> bool:
    if not args:
        return False

    first = args[0]
    if first in {"-h", "--help", "-V", "--version"}:
        return False
    if first.startswith("-"):
        return True
    return first not in commands


def _build_command(argv: List[str]) -> List[str]:
    version = _installed_version()
    binary = _ensure_binary(version)
    commands = _discover_subcommands(binary)

    if not argv:
        return [str(binary)]

    if argv[0] in {"-h", "--help"}:
        return [str(binary), "--help"]
    if argv[0] in {"-V", "--version"}:
        return [str(binary), "--version"]

    if _needs_check_subcommand(argv, commands):
        return [str(binary), "check", *argv]

    return [str(binary), *argv]


def main(argv: Iterable[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        command = _build_command(args)
    except RuffShimError as exc:
        print(exc, file=sys.stderr)
        return 1
    return subprocess.call(command)


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
