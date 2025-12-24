"""Trigger a default playblast using the packaged playblast tool."""

from __future__ import annotations

from libraries.creative.dcc.maya.playblast_tool import (
    PlayblastAutomationTool,
    PlayblastRequest,
)


def main() -> None:
    tool = PlayblastAutomationTool()
    request = PlayblastRequest(name="onepiece_panel_playblast")
    tool.playblast(request)


if __name__ == "__main__":
    main()
