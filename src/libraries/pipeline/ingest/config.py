"""Configuration loaders for pipeline-first ingest."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True)
class LinkRuleConfig:
    """Tag-driven linking rule definitions."""

    name: str
    target: str
    name_template: str = "{basename}"
    match_any_tags: tuple[str, ...] = ()
    match_all_tags: tuple[str, ...] = ()
    match_file_types: tuple[str, ...] = ()
    match_extensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class HookConfig:
    name: str
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeadlineActionConfig:
    enabled: bool = False
    pool: str | None = None
    group: str | None = None
    priority: int | None = None
    plugin: str | None = None
    extra_info: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeadlineConfig:
    optimize_model: DeadlineActionConfig = field(default_factory=DeadlineActionConfig)
    convert_to_usd: DeadlineActionConfig = field(default_factory=DeadlineActionConfig)


@dataclass(frozen=True)
class IngestConfig:
    link_rules: tuple[LinkRuleConfig, ...] = ()
    hooks: tuple[HookConfig, ...] = ()
    deadline: DeadlineConfig = field(default_factory=DeadlineConfig)


_DEFAULT_SCHEMA_VERSION = 1


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _normalize_rule_payload(raw: dict[str, Any]) -> LinkRuleConfig:
    match = raw.get("match", {}) if isinstance(raw.get("match"), dict) else {}
    return LinkRuleConfig(
        name=str(raw.get("name", "rule")),
        target=str(raw.get("target", "assets")),
        name_template=str(raw.get("name_template", "{basename}")),
        match_any_tags=tuple(str(tag) for tag in _coerce_list(match.get("any_tags"))),
        match_all_tags=tuple(str(tag) for tag in _coerce_list(match.get("all_tags"))),
        match_file_types=tuple(
            str(file_type) for file_type in _coerce_list(match.get("file_types"))
        ),
        match_extensions=tuple(
            str(ext).lower() for ext in _coerce_list(match.get("extensions"))
        ),
    )


def load_link_rules(path: Path) -> tuple[LinkRuleConfig, ...]:
    """Load link rule configuration from YAML or JSON."""

    payload = yaml.safe_load(path.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError("Link rule configuration must be a mapping")
    schema_version = payload.get("schema_version", _DEFAULT_SCHEMA_VERSION)
    if schema_version != _DEFAULT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported link rule schema version: {schema_version}")
    raw_rules = payload.get("rules", [])
    if not isinstance(raw_rules, Iterable):
        raise ValueError("Link rule configuration must include a list of rules")
    return tuple(_normalize_rule_payload(rule) for rule in raw_rules)


def _normalize_hook_payload(raw: dict[str, Any]) -> HookConfig:
    return HookConfig(
        name=str(raw.get("name", "hook")),
        enabled=bool(raw.get("enabled", True)),
        config=(
            dict(raw.get("config", {})) if isinstance(raw.get("config"), dict) else {}
        ),
    )


def _normalize_deadline_action(raw: dict[str, Any]) -> DeadlineActionConfig:
    return DeadlineActionConfig(
        enabled=bool(raw.get("enabled", False)),
        pool=raw.get("pool"),
        group=raw.get("group"),
        priority=raw.get("priority"),
        plugin=raw.get("plugin"),
        extra_info=(
            dict(raw.get("extra_info", {}))
            if isinstance(raw.get("extra_info"), dict)
            else {}
        ),
    )


def load_ingest_config(path: Path) -> IngestConfig:
    payload = yaml.safe_load(path.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError("Ingest configuration must be a mapping")
    schema_version = payload.get("schema_version", _DEFAULT_SCHEMA_VERSION)
    if schema_version != _DEFAULT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported ingest config schema version: {schema_version}")
    raw_rules = payload.get("link_rules", [])
    raw_hooks = payload.get("hooks", [])
    deadline_raw = payload.get("deadline", {})
    deadline = DeadlineConfig(
        optimize_model=_normalize_deadline_action(
            deadline_raw.get("optimize_model", {})
            if isinstance(deadline_raw, dict)
            else {}
        ),
        convert_to_usd=_normalize_deadline_action(
            deadline_raw.get("convert_to_usd", {})
            if isinstance(deadline_raw, dict)
            else {}
        ),
    )
    return IngestConfig(
        link_rules=tuple(
            _normalize_rule_payload(rule) for rule in _coerce_list(raw_rules)
        ),
        hooks=tuple(_normalize_hook_payload(hook) for hook in _coerce_list(raw_hooks)),
        deadline=deadline,
    )
