"""Rule engine for pipeline ingest planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RuleMatch:
    any_tags: tuple[str, ...] = ()
    all_tags: tuple[str, ...] = ()
    file_types: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    path_contains: tuple[str, ...] = ()
    min_size_bytes: int | None = None
    max_size_bytes: int | None = None


@dataclass(frozen=True)
class RuleOutput:
    target: str
    name_template: str = "{basename}"


@dataclass(frozen=True)
class RuleActions:
    hooks: tuple[str, ...] = ()
    deadline: tuple[str, ...] = ()


@dataclass(frozen=True)
class IngestRule:
    name: str
    priority: int
    match: RuleMatch
    outputs: tuple[RuleOutput, ...]
    actions: RuleActions


@dataclass(frozen=True)
class IngestRuleSet:
    rules: tuple[IngestRule, ...]


@dataclass(frozen=True)
class IngestPlan:
    links: tuple["PlannedLink", ...]
    hooks: tuple[str, ...]
    deadline_actions: tuple[str, ...]


@dataclass(frozen=True)
class PlannedLink:
    rule_name: str
    output: RuleOutput


_DEFAULT_SCHEMA_VERSION = 1


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _load_match(raw: dict[str, Any]) -> RuleMatch:
    match = raw.get("match", {}) if isinstance(raw.get("match"), dict) else {}
    return RuleMatch(
        any_tags=tuple(str(tag) for tag in _coerce_list(match.get("any_tags"))),
        all_tags=tuple(str(tag) for tag in _coerce_list(match.get("all_tags"))),
        file_types=tuple(
            str(file_type) for file_type in _coerce_list(match.get("file_types"))
        ),
        extensions=tuple(
            str(ext).lower() for ext in _coerce_list(match.get("extensions"))
        ),
        path_contains=tuple(
            str(path).lower() for path in _coerce_list(match.get("path_contains"))
        ),
        min_size_bytes=match.get("min_size_bytes"),
        max_size_bytes=match.get("max_size_bytes"),
    )


def _load_outputs(raw: dict[str, Any]) -> tuple[RuleOutput, ...]:
    outputs = _coerce_list(raw.get("outputs"))
    result: list[RuleOutput] = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        result.append(
            RuleOutput(
                target=str(output.get("target", "assets")),
                name_template=str(output.get("name_template", "{basename}")),
            )
        )
    return tuple(result)


def _load_actions(raw: dict[str, Any]) -> RuleActions:
    actions = raw.get("actions", {}) if isinstance(raw.get("actions"), dict) else {}
    return RuleActions(
        hooks=tuple(str(name) for name in _coerce_list(actions.get("hooks"))),
        deadline=tuple(str(name) for name in _coerce_list(actions.get("deadline"))),
    )


def load_ingest_rules(path: Path) -> IngestRuleSet:
    payload = yaml.safe_load(path.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError("Ingest rules must be a mapping")
    schema_version = payload.get("schema_version", _DEFAULT_SCHEMA_VERSION)
    if schema_version != _DEFAULT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported ingest rule schema version: {schema_version}")
    raw_rules = payload.get("rules", [])
    rules: list[IngestRule] = []
    for index, raw in enumerate(_coerce_list(raw_rules)):
        if not isinstance(raw, dict):
            continue
        rules.append(
            IngestRule(
                name=str(raw.get("name", f"rule_{index}")),
                priority=int(raw.get("priority", index)),
                match=_load_match(raw),
                outputs=_load_outputs(raw),
                actions=_load_actions(raw),
            )
        )
    rules_sorted = sorted(rules, key=lambda rule: (rule.priority, rule.name))
    return IngestRuleSet(rules=tuple(rules_sorted))


def _rule_matches(
    rule: IngestRule,
    *,
    tags: set[str],
    file_types: set[str],
    extensions: set[str],
    source_path: str,
    payload_size_bytes: int,
) -> bool:
    match = rule.match
    if match.any_tags and not tags.intersection(match.any_tags):
        return False
    if match.all_tags and not set(match.all_tags).issubset(tags):
        return False
    if match.file_types and not file_types.intersection(match.file_types):
        return False
    if match.extensions and not extensions.intersection(match.extensions):
        return False
    if match.path_contains:
        if not any(token in source_path for token in match.path_contains):
            return False
    if match.min_size_bytes is not None and payload_size_bytes < match.min_size_bytes:
        return False
    if match.max_size_bytes is not None and payload_size_bytes > match.max_size_bytes:
        return False
    return True


def plan_ingest(
    *,
    rules: IngestRuleSet,
    tags: set[str],
    file_types: set[str],
    extensions: set[str],
    source_path: str,
    payload_size_bytes: int,
) -> IngestPlan:
    link_outputs: list[PlannedLink] = []
    hook_actions: list[str] = []
    deadline_actions: list[str] = []
    for rule in rules.rules:
        if not _rule_matches(
            rule,
            tags=tags,
            file_types=file_types,
            extensions=extensions,
            source_path=source_path,
            payload_size_bytes=payload_size_bytes,
        ):
            continue
        for output in rule.outputs:
            link_outputs.append(PlannedLink(rule_name=rule.name, output=output))
        for hook_name in rule.actions.hooks:
            if hook_name not in hook_actions:
                hook_actions.append(hook_name)
        for deadline_name in rule.actions.deadline:
            if deadline_name not in deadline_actions:
                deadline_actions.append(deadline_name)
    return IngestPlan(
        links=tuple(link_outputs),
        hooks=tuple(hook_actions),
        deadline_actions=tuple(deadline_actions),
    )


def build_link_destination(
    *,
    output: RuleOutput,
    project_root: Path,
    asset_id: str,
    basename: str,
    source_uri: str,
    payload_name: str,
) -> Path:
    link_name = output.name_template.format(
        asset_id=asset_id,
        basename=basename,
        source_uri=source_uri,
        payload_name=payload_name,
    )
    return project_root / output.target / link_name
