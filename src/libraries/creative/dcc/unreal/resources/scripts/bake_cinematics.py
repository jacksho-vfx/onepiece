"""Queue render jobs for all level sequences using cinematic presets."""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def main() -> None:
    try:
        import unreal  # type: ignore
    except Exception:  # pragma: no cover - depends on Unreal runtime
        log.warning(
            "unreal.script.cinematics.unavailable",
            message="Unreal Python API unavailable; skipped cinematic bake",
        )
        return

    log.info("unreal.script.cinematics.start")
    tool_menus = getattr(unreal, "SequencerTools", None)
    if tool_menus is None:  # pragma: no cover - depends on Unreal runtime
        log.warning("unreal.script.cinematics.missing_tools")
        return

    sequences = tool_menus.list_available_level_sequences()
    for sequence in sequences:
        log.info(
            "unreal.script.cinematics.queue",
            sequence=str(sequence),
            destination="RenderQueue",
        )
        tool_menus.queue_render_job(sequence)

    log.info("unreal.script.cinematics.completed", count=len(sequences))


if __name__ == "__main__":
    main()
