"""Entry point for cleaning up the current Maya scene."""

from __future__ import annotations

from libraries.creative.dcc.maya.maya import cleanup_scene


def main() -> None:
    cleanup_scene()


if __name__ == "__main__":
    main()
