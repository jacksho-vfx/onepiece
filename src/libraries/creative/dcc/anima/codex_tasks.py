"""Codex tasks scoped to Anima."""

from __future__ import annotations

from libraries.creative.dcc.codex import CodexTask


ANIMA_CODEX_TASKS: tuple[CodexTask, ...] = (
    CodexTask(
        slug="anima-usd-crowd-publisher",
        title="USD Crowd Publisher",
        dcc="Anima",
        description=(
            "Bake crowd simulations to USD payloads with retime-safe clips and "
            "anim-aware material bindings for downstream DCCs."
        ),
        problem=(
            "Crowd caches exported as Alembic or FBX lose clip metadata and "
            "material overrides, making shot edits brittle."
        ),
        approach=(
            "Capture character clips, variations, and locomotion loops as USD "
            "payloads with authored primvars.",
            "Embed retime markers and root motion offsets so Nuke, Unreal, or "
            "Cinema4D can retime without re-simulating.",
            "Bundle per-agent material overrides and texture atlases for lighting "
            "consistency across DCCs.",
        ),
        deliverables=(
            "USD export preset for Anima",
            "Retime-aware cache metadata schema",
            "Material override map per agent archetype",
        ),
        dependencies=("Anima SDK", "USD payload authoring"),
    ),
)

__all__ = ["ANIMA_CODEX_TASKS"]
