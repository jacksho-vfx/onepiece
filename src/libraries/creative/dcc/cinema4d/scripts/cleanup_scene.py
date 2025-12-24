"""Perform a quick cleanup pass of the active Cinema 4D scene."""

from __future__ import annotations

from libraries.creative.dcc.cinema4d.cleanup import cleanup_scene


def main() -> None:
    """Execute the shared cleanup helper with friendly error handling."""

    try:
        stats = cleanup_scene()
    except Exception as exc:  # pragma: no cover - runtime depends on Cinema 4D
        print(f"Cinema 4D cleanup failed: {exc}")
        return

    summary = (
        f"Removed {stats.get('removed_materials', 0)} materials, "
        f"{stats.get('removed_empty_nulls', 0)} empty nulls, "
        f"{stats.get('removed_hidden_singletons', 0)} hidden objects, "
        f"{stats.get('removed_layers', 0)} unused layers."
    )
    print(summary)


if __name__ == "__main__":  # pragma: no cover - exercised inside DCC
    main()
