"""Utilities for parsing shot and version identifiers from paths and keys."""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Iterable, Optional

import structlog

from libraries.validations.naming import (
    validate_asset_name,
    validate_shot,
    validate_shot_name,
)

log = structlog.get_logger(__name__)

SHOT_TOKEN_PATTERN = re.compile(r"(ep\d{3}_sc\d{2}_\d{4})", re.IGNORECASE)
ASSET_TOKEN_PATTERN = re.compile(r"(ep\d{3}_sc\d{2}_\d{4}_[a-zA-Z0-9]+)", re.IGNORECASE)
VERSION_PATTERN = re.compile(r"v(?P<num>\d{2,4})", re.IGNORECASE)


def _normalise_version(value: str) -> str:
    number = int(value)
    return f"v{number:03d}"


def extract_version(parts: Iterable[str]) -> Optional[str]:
    """Return the first matching version token from *parts*."""

    for part in parts:
        match = VERSION_PATTERN.search(part)
        if not match:
            continue
        try:
            return _normalise_version(match.group("num"))
        except ValueError:
            log.debug("parse.invalid_version", token=part)
    return None


def _extract_from_token(candidate: str, scope: str) -> Optional[str]:
    if scope == "assets":
        if validate_asset_name(candidate):
            return candidate.lower()
        match = ASSET_TOKEN_PATTERN.search(candidate)
        if match and validate_asset_name(match.group(1)):
            return match.group(1).lower()
    else:
        if validate_shot_name(candidate):
            return candidate.lower()
        match = SHOT_TOKEN_PATTERN.search(candidate)
        if match and validate_shot_name(match.group(1)):
            return match.group(1).lower()
        if validate_shot(candidate):
            return candidate.lower()
    return None


def extract_entity(parts: Iterable[str], scope: str) -> Optional[str]:
    """Return the first entity token matching the provided *scope*."""

    for part in parts:
        result = _extract_from_token(part, scope)
        if result:
            return result
    return None


def extract_from_path(path: PurePath, scope: str) -> tuple[Optional[str], Optional[str]]:
    """Extract entity and version identifiers from a filesystem path."""

    parts = list(path.parts)
    entity = extract_entity(parts + [path.name], scope=scope)
    version = extract_version(parts + [path.name])
    return entity, version
