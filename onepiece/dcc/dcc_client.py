"""Utilities for interacting with DCC applications.

This module intentionally keeps a very small public surface so that it can be
used in both the CLI application and by external tooling.  Only the features
needed by the tests are implemented which keeps the behaviour easy to reason
about.
"""

from enum import Enum
from pathlib import Path
import subprocess

__all__ = ["SupportedDCC", "open_scene"]


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

        return self.value


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
