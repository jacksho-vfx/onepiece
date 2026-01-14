"""Tag-driven link resolution for pipeline ingest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from libraries.pipeline.ingest.config import LinkRuleConfig
from libraries.pipeline.ingest.metadata import IngestMetadata


@dataclass(frozen=True)
class IngestLink:
    rule_name: str
    source: Path
    destination: Path


@dataclass(frozen=True)
class LinkMatchContext:
    tags: set[str]
    file_types: set[str]
    extensions: set[str]


def _rule_matches(rule: LinkRuleConfig, context: LinkMatchContext) -> bool:
    if rule.match_any_tags and not context.tags.intersection(rule.match_any_tags):
        return False
    if rule.match_all_tags and not set(rule.match_all_tags).issubset(context.tags):
        return False
    if rule.match_file_types and not context.file_types.intersection(
        rule.match_file_types
    ):
        return False
    if rule.match_extensions and not context.extensions.intersection(
        rule.match_extensions
    ):
        return False
    return True


def _build_link_name(
    rule: LinkRuleConfig, metadata: IngestMetadata, basename: str
) -> str:
    return str(
        rule.name_template.format(
            asset_id=metadata.asset_id,
            basename=basename,
            source_uri=metadata.source_uri,
        )
    )


def resolve_links(
    *,
    rules: Iterable[LinkRuleConfig],
    metadata: IngestMetadata,
    project_root: Path,
    payload: Path,
    payload_basename: str,
    payload_extensions: set[str],
) -> tuple[IngestLink, ...]:
    context = LinkMatchContext(
        tags=set(metadata.tags.get("freeform", []))
        | set(metadata.tags.get("controlled", [])),
        file_types=set(metadata.file_types),
        extensions=payload_extensions,
    )
    links: list[IngestLink] = []
    for rule in rules:
        if not _rule_matches(rule, context):
            continue
        link_name = _build_link_name(rule, metadata, payload_basename)
        destination = project_root / rule.target / link_name
        links.append(
            IngestLink(rule_name=rule.name, source=payload, destination=destination)
        )
    return tuple(links)
