"""Pipeline-first ingest CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from libraries.pipeline.ingest import (
    IngestConfig,
    ingest_asset,
    load_ingest_config,
    load_link_rules,
)

app = typer.Typer(name="pipeline", help="Ingest assets into the .pipeline store.")


def _parse_relationships(values: list[str]) -> list[dict[str, str]]:
    relationships: list[dict[str, str]] = []
    for value in values:
        if "=" not in value:
            raise typer.BadParameter("Relationships must be in key=value format")
        key, relation_value = value.split("=", 1)
        relationships.append({"type": key, "target": relation_value})
    return relationships


@app.command("asset")
def ingest_asset_command(
    source: Path = typer.Argument(..., help="Source file or directory to ingest."),
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        help="Project root containing the .pipeline directory.",
    ),
    rules: Optional[Path] = typer.Option(
        None,
        "--rules",
        help="Path to the tag-to-link rules config file.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Optional ingest pipeline config (hooks, Deadline actions, link rules).",
    ),
    tag: list[str] = typer.Option(
        None,
        "--tag",
        help="Freeform tag to attach to the ingest. Can be repeated.",
    ),
    controlled_tag: list[str] = typer.Option(
        None,
        "--controlled-tag",
        help="Controlled tag to attach to the ingest. Can be repeated.",
    ),
    relationship: list[str] = typer.Option(
        None,
        "--relationship",
        help="Relationship metadata in key=value format. Can be repeated.",
    ),
    asset_id: Optional[str] = typer.Option(
        None,
        "--asset-id",
        help="Optional stable asset ID to reuse.",
    ),
) -> None:
    """Ingest a source payload into the canonical .pipeline store."""

    ingest_config = IngestConfig()
    if config:
        ingest_config = load_ingest_config(config)
    if rules:
        ingest_config = IngestConfig(
            link_rules=load_link_rules(rules),
            hooks=ingest_config.hooks,
            deadline=ingest_config.deadline,
        )
    if not ingest_config.link_rules:
        raise typer.BadParameter(
            "No link rules found. Provide --rules or config with link_rules."
        )

    result = ingest_asset(
        source=source,
        project_root=project_root,
        config=ingest_config,
        asset_id=asset_id,
        tags=tag or [],
        controlled_tags=controlled_tag or [],
        relationships=_parse_relationships(relationship or []),
    )
    typer.echo(f"Ingested asset {result.asset_id} to {result.asset_dir}")
    for link in result.links:
        typer.echo(f"Linked {link.destination} -> {link.source}")
