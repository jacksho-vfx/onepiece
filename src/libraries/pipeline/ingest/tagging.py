"""Tag inference and validation for pipeline ingest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from libraries.pipeline.ingest.payload import PayloadManifest, build_payload_manifest


@dataclass(frozen=True)
class TagVocabulary:
    allowed_tags: set[str]
    namespaces: dict[str, set[str]]
    required_namespaces: set[str]


def load_tag_vocabulary(project_root: Path) -> TagVocabulary:
    config_path = project_root / ".pipeline" / "tags.yaml"
    if not config_path.exists():
        return TagVocabulary(
            allowed_tags=set(), namespaces={}, required_namespaces=set()
        )
    import yaml  # type: ignore[import-untyped]

    payload = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(payload, dict):
        raise ValueError("Tag vocabulary must be a mapping")
    allowed = {str(tag) for tag in payload.get("allowed", [])}
    namespaces: dict[str, set[str]] = {}
    raw_namespaces = payload.get("namespaces", {})
    if isinstance(raw_namespaces, dict):
        for key, values in raw_namespaces.items():
            if isinstance(values, dict):
                values = values.get("allowed", [])
            namespaces[str(key)] = {str(value) for value in values or []}
    required = {str(name) for name in payload.get("required", [])}
    return TagVocabulary(
        allowed_tags=allowed,
        namespaces=namespaces,
        required_namespaces=required,
    )


def _split_tags(tags: list[str]) -> tuple[list[str], list[str]]:
    freeform: list[str] = []
    controlled: list[str] = []
    for tag in tags:
        if ":" in tag:
            controlled.append(tag)
        else:
            freeform.append(tag)
    return freeform, controlled


_PATH_TAGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("/plates/", ("plates", "dept:plates")),
    ("/assets/char/", ("asset_type:char",)),
    ("/assets/env/", ("asset_type:env",)),
    ("/assets/prop/", ("asset_type:prop",)),
    ("/assets/", ("assets",)),
)


def infer_tags(
    source: Path,
    *,
    manifest: PayloadManifest | None = None,
    user_tags: list[str] | None = None,
    controlled_tags: list[str] | None = None,
) -> dict[str, list[str]]:
    manifest = manifest or build_payload_manifest(source)
    tags: list[str] = []
    for file_type in manifest.file_types:
        tags.append(f"file_type:{file_type}")
    for ext in sorted(ext for ext in manifest.extensions if ext):
        tags.append(f"ext:{ext.lstrip('.')}")
    source_str = source.as_posix().lower()
    for needle, tag_values in _PATH_TAGS:
        if needle in source_str:
            tags.extend(tag_values)
    tags.extend(user_tags or [])
    tags.extend(controlled_tags or [])
    freeform, controlled = _split_tags(sorted(set(tags)))
    return {"freeform": freeform, "controlled": controlled}


@dataclass(frozen=True)
class TagValidationResult:
    is_valid: bool
    errors: tuple[str, ...]


def validate_tags(
    tags: dict[str, list[str]], vocabulary: TagVocabulary
) -> TagValidationResult:
    errors: list[str] = []
    if not vocabulary.allowed_tags and not vocabulary.namespaces:
        return TagValidationResult(is_valid=True, errors=())

    def _allowed(tag_value: str) -> bool:
        if tag_value in vocabulary.allowed_tags:
            return True
        if ":" not in tag_value:
            return not vocabulary.allowed_tags or tag_value in vocabulary.allowed_tags
        namespace, value = tag_value.split(":", 1)
        allowed_values = vocabulary.namespaces.get(namespace, set())
        if not allowed_values:
            return False
        return value in allowed_values

    provided_tags = set(tags.get("freeform", [])) | set(tags.get("controlled", []))
    for tag_value in sorted(provided_tags):
        if not _allowed(tag_value):
            errors.append(f"Tag '{tag_value}' is not allowed.")

    for namespace in sorted(vocabulary.required_namespaces):
        if not any(tag.startswith(f"{namespace}:") for tag in provided_tags):
            allowed_values = vocabulary.namespaces.get(namespace, set())
            suggestion = (
                f" Allowed values: {', '.join(sorted(allowed_values))}."
                if allowed_values
                else ""
            )
            errors.append(f"Missing required namespace '{namespace}'.{suggestion}")

    return TagValidationResult(is_valid=not errors, errors=tuple(errors))
