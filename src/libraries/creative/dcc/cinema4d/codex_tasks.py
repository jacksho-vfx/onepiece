"""Codex tasks scoped to Cinema4D."""

from __future__ import annotations

from libraries.creative.dcc.codex import CodexTask


CINEMA4D_CODEX_TASKS: tuple[CodexTask, ...] = (
    CodexTask(
        slug="cinema4d-usd-stage-sanitiser",
        title="USD Stage Sanitiser",
        dcc="Cinema4D",
        description=(
            "Automate scale, axis, and naming cleanup for USD stages authored in "
            "Cinema4D before they flow to Unreal, Nuke, or the farm."
        ),
        problem=(
            "Inconsistent units, pivot orientations, and dirty object names slip "
            "through layout, causing broken references and transforms down the "
            "line."
        ),
        approach=(
            "Normalise scene scale, axis alignment, and up-axis metadata on export.",
            "Enforce naming and variant conventions for shots, assets, and cameras.",
            "Generate a USD validation report highlighting problematic prims before "
            "publish.",
        ),
        deliverables=(
            "Cinema4D command plugin for pre-publish cleanup",
            "USD report summarising fixes and outstanding issues",
            "Configurable naming and unit ruleset for shows",
        ),
        dependencies=("USD Python bindings", "Cinema4D Python API"),
    ),
    CodexTask(
        slug="cinema4d-redshift-asset-relinker",
        title="Redshift Asset Relinker",
        dcc="Cinema4D",
        description=(
            "Relink Redshift proxies, textures, and caches to USD-friendly paths so "
            "packaging for Deadline or Unreal stays deterministic."
        ),
        problem=(
            "Artists often stash textures on workstations or network shares that "
            "are invisible to the farm or game ingest, leading to black renders."
        ),
        approach=(
            "Scan materials and cache loaders for external references and remap them "
            "to studio packages or OCIO-aware search paths.",
            "Emit a manifest of remapped assets and copy missing files into the "
            "show package with checksum validation.",
            "Provide a dry-run mode that only reports issues for supervisors to "
            "review before auto-fixing.",
        ),
        deliverables=(
            "Relink CLI and Cinema4D shelf button",
            "JSON manifest of remapped and missing assets",
            "Checksum-based copier for packaging",
        ),
        dependencies=("Redshift", "OCIO config", "Studio package layout"),
    ),
)

__all__ = ["CINEMA4D_CODEX_TASKS"]
