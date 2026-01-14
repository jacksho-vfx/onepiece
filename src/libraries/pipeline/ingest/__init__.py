"""Tag-driven ingest pipeline utilities."""

from libraries.pipeline.ingest.config import (
    DeadlineActionConfig,
    DeadlineConfig,
    HookConfig,
    IngestConfig,
    LinkRuleConfig,
    load_ingest_config,
    load_link_rules,
)
from libraries.pipeline.ingest.hooks import (
    HookRegistry,
    IngestHook,
    register_hook,
)
from libraries.pipeline.ingest.linking import IngestLink, resolve_links
from libraries.pipeline.ingest.metadata import IngestMetadata, IngestMetadataFile
from libraries.pipeline.ingest.service import IngestResult, ingest_asset

__all__ = [
    "DeadlineActionConfig",
    "DeadlineConfig",
    "HookConfig",
    "HookRegistry",
    "IngestConfig",
    "IngestHook",
    "IngestLink",
    "IngestMetadata",
    "IngestMetadataFile",
    "IngestResult",
    "LinkRuleConfig",
    "ingest_asset",
    "load_ingest_config",
    "load_link_rules",
    "register_hook",
    "resolve_links",
]
