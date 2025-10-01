from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

from libraries.aws.scanner import scan_s3_context

__all__ = [
    "check_shot_versions_local",
    "check_shot_versions_s3",
    "S3ParityReport",
]


@dataclass(frozen=True)
class S3ParityReport:
    """Summary of parity checks between an expected manifest and S3."""

    missing: dict[str, list[str]]
    unexpected: dict[str, list[str]]

    @property
    def is_clean(self) -> bool:
        """Return ``True`` when S3 contains exactly the expected versions."""

        return not self.missing and not self.unexpected


def _normalise_key(value: str) -> str:
    return value.replace("\\", "/").lower()


def _normalise_version(value: str) -> str:
    return value.strip().lower()


def _build_expected_manifest(
    shot_versions: Mapping[str, Sequence[str]]
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Return lookup tables for expected entities and their versions."""

    display_names: dict[str, str] = {}
    manifest: dict[str, dict[str, str]] = {}
    for shot, versions in shot_versions.items():
        normalised_shot = _normalise_key(shot)
        display_names.setdefault(normalised_shot, shot)
        version_lookup = manifest.setdefault(normalised_shot, {})
        for version in versions:
            normalised_version = _normalise_version(str(version))
            if not normalised_version:
                continue
            version_lookup.setdefault(normalised_version, str(version))
    return display_names, manifest


def _collect_s3_versions(
    project_name: str,
    context: str,
    *,
    scope: str = "shots",
    bucket: str | None = None,
    s3_client: object | None = None,
) -> tuple[dict[str, str], MutableMapping[str, set[str]]]:
    """Return the versions that exist in S3 grouped by entity."""

    results = scan_s3_context(
        project_name,
        context,
        scope=scope,
        bucket=bucket,
        s3_client=s3_client,
    )
    display_names: dict[str, str] = {}
    versions: MutableMapping[str, set[str]] = defaultdict(set)
    for entry in results:
        shot = entry.get("shot")
        version = entry.get("version")
        if not shot or not version:
            continue
        normalised_shot = _normalise_key(shot)
        normalised_version = _normalise_version(version)
        display_names.setdefault(normalised_shot, shot)
        versions[normalised_shot].add(normalised_version)
    return display_names, versions


def check_shot_versions_local(
    shot_versions: Mapping[str, Sequence[str]], local_base: Path
) -> dict[str, list[str]]:
    """Return versions missing on disk for each shot or asset in ``shot_versions``."""

    missing: dict[str, list[str]] = {}
    for shot, versions in shot_versions.items():
        absent: list[str] = []
        for version in versions:
            version_path = local_base / shot / str(version)
            if not version_path.exists():
                absent.append(str(version))
        if absent:
            missing[shot] = absent
    return missing


def check_shot_versions_s3(
    shot_versions: Mapping[str, Sequence[str]],
    project_name: str,
    context: str,
    *,
    scope: str = "shots",
    bucket: str | None = None,
    s3_client: object | None = None,
) -> S3ParityReport:
    """Return a parity report comparing ``shot_versions`` to objects present in S3."""

    expected_display, expected_manifest = _build_expected_manifest(shot_versions)
    s3_display, s3_versions = _collect_s3_versions(
        project_name,
        context,
        scope=scope,
        bucket=bucket,
        s3_client=s3_client,
    )

    missing: dict[str, list[str]] = {}
    unexpected: dict[str, list[str]] = {}

    for normalised_shot, versions_lookup in expected_manifest.items():
        expected_versions = set(versions_lookup.keys())
        available_versions = s3_versions.get(normalised_shot, set())

        missing_versions = sorted(
            versions_lookup[version] for version in expected_versions - available_versions
        )
        if missing_versions:
            missing[expected_display[normalised_shot]] = missing_versions

        unexpected_versions = sorted(
            _normalise_version(version)
            for version in available_versions - expected_versions
        )
        if unexpected_versions:
            display_name = expected_display.get(normalised_shot)
            if display_name is None:
                display_name = s3_display.get(normalised_shot, normalised_shot)
            unexpected[display_name] = unexpected_versions

    for normalised_shot, versions in s3_versions.items():
        if normalised_shot in expected_manifest:
            continue
        display_name = s3_display.get(normalised_shot, normalised_shot)
        unexpected[display_name] = sorted(_normalise_version(v) for v in versions)

    return S3ParityReport(missing=missing, unexpected=unexpected)
