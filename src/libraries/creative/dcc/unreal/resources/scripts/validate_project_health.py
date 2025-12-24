"""Audit lighting, plugins, and maps for export readiness."""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def main() -> None:
    try:
        import unreal  # type: ignore
    except Exception:  # pragma: no cover - depends on Unreal runtime
        log.warning(
            "unreal.script.validation.unavailable",
            message="Unreal Python API unavailable; skipped validation run",
        )
        return

    log.info("unreal.script.validation.start")
    validator = getattr(unreal, "EditorValidatorSubsystem", None)
    if validator is None:  # pragma: no cover - depends on Unreal runtime
        log.warning("unreal.script.validation.missing_subsystem")
        return

    report = validator.validate_loaded_assets()
    log.info(
        "unreal.script.validation.summary",
        errors=report.get_num_failed_assets(),
        warnings=report.get_num_warnings(),
    )


if __name__ == "__main__":
    main()
