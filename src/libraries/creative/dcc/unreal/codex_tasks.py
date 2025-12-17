"""Codex tasks scoped to Unreal Engine."""

from __future__ import annotations

from libraries.creative.dcc.codex import CodexTask


UNREAL_CODEX_TASKS: tuple[CodexTask, ...] = (
    CodexTask(
        slug="unreal-usd-level-ingestor",
        title="USD Level Ingestor",
        dcc="Unreal",
        description=(
            "Convert staged USD shots into Unreal levels with sequencer bindings, "
            "preserving variants and references for archviz walkthroughs."
        ),
        problem=(
            "Manual USD imports lose variant selections, timecodes, or light links, "
            "forcing repeated rebuilds of the same level."
        ),
        approach=(
            "Translate USD stage composition into level streaming hierarchies and "
            "sequencer tracks.",
            "Map USD variants and prim metadata to Unreal Level Variant Sets and "
            "Blueprint tags.",
            "Cache import tasks so iterative updates keep GUIDs stable for lighting "
            "and collisions.",
        ),
        deliverables=(
            "Batch import utility for USD shots",
            "Variant-preserving sequencer template",
            "GUID-stable refresh workflow",
        ),
        dependencies=("USD Stage import", "Level Variant Sets", "Sequencer API"),
    ),
    CodexTask(
        slug="unreal-lightmap-budget-audit",
        title="Lightmap Budget Audit",
        dcc="Unreal",
        description=(
            "Inspect USD-authored meshes for lightmap, Nanite, and LOD budgets "
            "before they reach the render farm or packaged build."
        ),
        problem=(
            "Over-budget lightmaps and mismatched Nanite/LOD settings tank build "
            "times and introduce lighting noise in architectural flythroughs."
        ),
        approach=(
            "Analyse mesh metadata for lightmap UV density, Nanite eligibility, and "
            "LOD coverage during USD ingest.",
            "Generate actionable recommendations (e.g. texel density targets, auto "
            "LOD generation) and optionally patch settings in place.",
            "Surface a scorecard to track regression across publishes and enforce "
            "per-sequence budgets.",
        ),
        deliverables=(
            "USD-aware mesh audit report",
            "Auto-tuning helpers for lightmap resolution and LODs",
            "Scorecard summarising per-shot budget health",
        ),
        dependencies=("Mesh Metadata", "Unreal Python API"),
    ),
)

__all__ = ["UNREAL_CODEX_TASKS"]
