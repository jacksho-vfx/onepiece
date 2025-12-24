"""Run the OnePiece animation debugger inside Maya."""

from __future__ import annotations

from libraries.creative.dcc.maya.animation_debugger import debug_animation


def main() -> None:
    debug_animation()


if __name__ == "__main__":
    main()
