"""Mount project shares, maps, and collections into the current Unreal session."""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def main() -> None:
    try:
        import unreal  # type: ignore
    except Exception:  # pragma: no cover - depends on Unreal runtime
        log.warning(
            "unreal.script.environment.unavailable",
            message="Unreal Python API unavailable; skipped environment setup",
        )
        return

    log.info("unreal.script.environment.start")
    project_name = getattr(unreal, "SystemLibrary", None)
    tool = getattr(unreal, "PythonBPLib", None)
    if (
        project_name is None or tool is None
    ):  # pragma: no cover - depends on Unreal runtime
        log.warning("unreal.script.environment.missing_api")
        return

    project_root = tool.get_project_content_directory()
    log.info("unreal.script.environment.content_root", project_root=project_root)
    collections = tool.list_asset_collections()
    for collection in collections:
        log.info("unreal.script.environment.collection", name=str(collection))

    log.info("unreal.script.environment.completed", collections=len(collections))


if __name__ == "__main__":
    main()
