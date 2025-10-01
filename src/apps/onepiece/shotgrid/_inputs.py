"""Helpers for loading structured JSON/YAML data for ShotGrid CLIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import structlog

from apps.onepiece.utils.errors import OnePieceIOError, OnePieceValidationError

log = structlog.get_logger(__name__)

try:  # pragma: no cover - exercised indirectly when YAML is available
    import yaml
except Exception:  # noqa: BLE001 - fall back to JSON-only mode
    yaml = None  # type: ignore[assignment]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 - surfaced to CLI as IO error
        log.error("shotgrid.input.read_failed", path=str(path), error=str(exc))
        raise OnePieceIOError(f"Failed to read input file '{path}': {exc}") from exc


def _candidate_parsers(path: Path) -> list[tuple[str, Callable[[str], Any]]]:
    suffix = path.suffix.lower()

    parsers: list[tuple[str, Callable[[str], Any]]] = [("json", json.loads)]

    if yaml is not None:
        parsers.append(("yaml", yaml.safe_load))

    if suffix in {".yaml", ".yml"} and yaml is not None:
        return [("yaml", yaml.safe_load), ("json", json.loads)]
    if suffix == ".json":
        return parsers
    return parsers


def load_structured_data(path: Path) -> Any:
    """Load a JSON or YAML payload from ``path``."""

    raw = _read_text(path)

    errors: list[str] = []
    for label, parser in _candidate_parsers(path):
        try:
            payload = parser(raw)
        except Exception as exc:  # noqa: BLE001 - recorded for diagnostics
            errors.append(f"{label}: {exc}")
            continue

        if payload is None:
            errors.append(f"{label}: empty document")
            continue

        return payload

    log.error("shotgrid.input.invalid_payload", path=str(path), errors=errors)
    if yaml is None:
        hint = "JSON"
    else:
        hint = "JSON or YAML"
    raise OnePieceValidationError(
        f"Input file '{path}' must contain valid {hint} content."
    )


def load_structured_array(path: Path) -> list[Any]:
    """Load a JSON/YAML array from ``path``."""

    payload = load_structured_data(path)
    if not isinstance(payload, list):
        raise OnePieceValidationError(
            f"Input file '{path}' must contain a JSON/YAML array."
        )
    return payload


def load_structured_mapping(path: Path) -> dict[str, Any]:
    """Load a JSON/YAML mapping from ``path``."""

    payload = load_structured_data(path)
    if not isinstance(payload, dict):
        raise OnePieceValidationError(
            f"Input file '{path}' must contain a JSON/YAML object."
        )
    return payload
