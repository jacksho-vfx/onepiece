from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from tools import usd_bundler

# Re-use the USD parsing helpers from usd_bundler so variant selection semantics
# stay consistent across tooling. The underscore-prefixed names are considered
# private but provide the behaviour we need for controlled test fixtures.
_VARIANT_SET_PATTERN = usd_bundler._VARIANT_SET_PATTERN
_VARIANT_SELECTION_PATTERN = usd_bundler._VARIANT_SELECTION_PATTERN
_STRING_SELECTION_PATTERN = usd_bundler._STRING_SELECTION_PATTERN
_ASSET_PATTERN = usd_bundler._ASSET_PATTERN
_find_matching_brace = usd_bundler._find_matching_brace
_prune_variant_sets = usd_bundler._prune_variant_sets
_apply_variant_metadata = usd_bundler._apply_variant_metadata


@dataclass(frozen=True)
class VariantOption:
    """A single selectable option inside a variant set."""

    name: str
    payloads: tuple[Path, ...]
    raw_payloads: tuple[str, ...]


@dataclass(frozen=True)
class VariantSet:
    """Description of a variant set on the stage."""

    name: str
    options: tuple[VariantOption, ...]
    active_selection: str | None

    def option_names(self) -> tuple[str, ...]:
        return tuple(option.name for option in self.options)

    def option_payloads(self, option_name: str) -> VariantOption:
        for option in self.options:
            if option.name == option_name:
                return option
        msg = f"Variant option '{option_name}' not found for set '{self.name}'"
        raise KeyError(msg)


@dataclass(frozen=True)
class VariantActivation:
    """Result of switching a variant selection."""

    set_name: str
    selection: str
    relinked_payloads: Mapping[str, str]
    stage_path: Path


class StageVariants:
    """Utility for inspecting and switching USD variant sets."""

    def __init__(self, stage_path: Path, *, search_paths: Sequence[Path] | None = None):
        self.stage_path = stage_path
        self.search_paths = tuple(search_paths or ())

    def list_variants(self) -> tuple[VariantSet, ...]:
        text = self.stage_path.read_text()
        selections = _parse_active_variants(text)
        return _parse_variant_sets(text, selections, base_dir=self.stage_path.parent)

    def activate(
        self,
        set_name: str,
        selection: str,
        *,
        refresh_viewport: Callable[[], None] | None = None,
    ) -> VariantActivation:
        text = self.stage_path.read_text()
        selections = _parse_active_variants(text)
        variant_sets = _parse_variant_sets(
            text, selections, base_dir=self.stage_path.parent
        )
        target_set = _find_variant_set(variant_sets, set_name)
        if selection not in target_set.option_names():
            available = ", ".join(target_set.option_names())
            msg = f"Unknown selection '{selection}' for variant set '{set_name}'. Available: {available}"
            raise KeyError(msg)

        selections[set_name] = selection
        updated = _prune_variant_sets(text, {set_name: selection})
        updated = _apply_variant_metadata(updated, selections)

        option = target_set.option_payloads(selection)
        replacements = self._relink_payloads(option, base_dir=self.stage_path.parent)
        updated = _rewrite_payload_paths(updated, replacements)
        self.stage_path.write_text(updated)

        if refresh_viewport:
            refresh_viewport()

        return VariantActivation(
            set_name=set_name,
            selection=selection,
            relinked_payloads=replacements,
            stage_path=self.stage_path,
        )

    def _relink_payloads(
        self, option: VariantOption, *, base_dir: Path
    ) -> dict[str, str]:
        replacements: dict[str, str] = {}
        search_roots = (base_dir, *self.search_paths)
        for raw, payload in zip(option.raw_payloads, option.payloads):
            resolved = _resolve_payload(payload, search_roots)
            if resolved:
                replacements[raw] = str(resolved)
        return replacements


def _resolve_payload(candidate: Path, search_roots: Iterable[Path]) -> Path | None:
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if candidate.exists():
        return candidate.resolve()

    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return None


def _parse_active_variants(text: str) -> dict[str, str]:
    selections: dict[str, str] = {}
    for block in _VARIANT_SELECTION_PATTERN.findall(text):
        for match in _STRING_SELECTION_PATTERN.finditer(block):
            selections[match.group("name")] = match.group("value")
    return selections


def _parse_variant_sets(
    text: str, selections: Mapping[str, str], *, base_dir: Path | None
) -> tuple[VariantSet, ...]:
    cursor = 0
    sets: list[VariantSet] = []
    while True:
        match = _VARIANT_SET_PATTERN.search(text, cursor)
        if not match:
            break
        set_name = match.group("name")
        open_index = text.find("{", match.end() - 1)
        close_index = _find_matching_brace(text, open_index)
        body = text[open_index + 1 : close_index]
        options = _parse_variant_options(body, base_dir=base_dir)
        sets.append(
            VariantSet(
                name=set_name,
                options=tuple(options),
                active_selection=selections.get(set_name),
            )
        )
        cursor = close_index + 1
    return tuple(sets)


def _parse_variant_options(body: str, *, base_dir: Path | None) -> list[VariantOption]:
    options: list[VariantOption] = []
    option_pattern = re.compile(r'"(?P<name>[^"]+)"\s*{')
    search_offset = 0
    while True:
        match = option_pattern.search(body, search_offset)
        if not match:
            break
        name = match.group("name")
        open_index = body.find("{", match.end() - 1)
        close_index = _find_matching_brace(body, open_index)
        option_body = body[open_index + 1 : close_index]
        raw_payloads = tuple(
            match.group("path") for match in _ASSET_PATTERN.finditer(option_body)
        )
        payloads = tuple(_resolve_asset(raw, base_dir) for raw in raw_payloads)
        options.append(
            VariantOption(
                name=name,
                payloads=payloads,
                raw_payloads=raw_payloads,
            )
        )
        search_offset = close_index + 1
    return options


def _resolve_asset(raw_path: str, base_dir: Path | None) -> Path:
    path = Path(raw_path)
    if not path.is_absolute() and base_dir is not None:
        return (base_dir / path).resolve()
    return path.resolve() if path.exists() else path


def _rewrite_payload_paths(text: str, replacements: Mapping[str, str]) -> str:
    updated = text
    for raw, resolved in replacements.items():
        updated = updated.replace(f"@{raw}@", f"@{resolved}@")
    return updated


def _find_variant_set(variant_sets: Sequence[VariantSet], set_name: str) -> VariantSet:
    for variant_set in variant_sets:
        if variant_set.name == set_name:
            return variant_set
    msg = f"Variant set '{set_name}' not present on stage"
    raise KeyError(msg)


__all__ = [
    "StageVariants",
    "VariantActivation",
    "VariantOption",
    "VariantSet",
]
