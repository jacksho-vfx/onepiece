"""Checksum reporting helpers for ingest inputs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence, cast

import typer

from apps.onepiece.utils.errors import OnePieceValidationError
from libraries.automation.delivery.manifest import compute_checksum
from libraries.automation.ingest.manifest import (
    Delivery,
    DeliveryManifestError,
    _build_manifest_index,
    load_delivery_manifest,
)

ReportFormat = Literal["json", "text"]
ChecksumStatus = Literal["ok", "mismatch", "computed", "missing"]


@dataclass
class FileChecksum:
    """Checksum information for a single file."""

    path: Path
    size: int
    checksum: str
    status: ChecksumStatus
    expected_checksum: str | None = None
    manifest: Mapping[str, object] | None = None


@dataclass
class ChecksumReport:
    """Collection of checksum entries and manifest coverage details."""

    files: list[FileChecksum]
    missing_from_manifest: list[Mapping[str, object]]

    @property
    def summary(self) -> Mapping[str, int]:
        mismatches = sum(1 for entry in self.files if entry.status == "mismatch")
        matched = sum(1 for entry in self.files if entry.expected_checksum)
        return {
            "files_scanned": len(self.files),
            "mismatched_files": mismatches,
            "files_with_manifest": matched,
            "missing_manifest_entries": len(self.missing_from_manifest),
        }


def _iter_input_files(paths: Sequence[Path]) -> Iterable[tuple[Path, Path]]:
    for entry in paths:
        if not entry.exists():
            raise OnePieceValidationError(f"Path does not exist: {entry}")

        if entry.is_file():
            yield entry, entry.parent
            continue

        for file_path in sorted(entry.rglob("*")):
            if file_path.is_file():
                yield file_path, entry


def _serialise_delivery(delivery: Delivery) -> Mapping[str, object]:
    data = asdict(delivery)
    data["source_path"] = str(delivery.source_path)
    data["delivery_path"] = str(delivery.delivery_path)
    return data


def _normalise_checksum(value: str | None, algorithm: str) -> str | None:
    if value is None:
        return None

    lower = value.lower()
    prefix = f"{algorithm.lower()}:"
    if lower.startswith(prefix):
        return lower[len(prefix) :]
    return lower


def _match_manifest_entry(
    path: Path, *, root: Path, manifest_index: Mapping[str, Delivery]
) -> Delivery | None:
    relative = path.relative_to(root).as_posix()
    for key in (relative, path.name):
        matched = manifest_index.get(key)
        if matched:
            return matched
    return None


def build_checksum_report(
    inputs: Sequence[Path],
    *,
    manifest_entries: Sequence[Delivery] | None = None,
    algorithm: str = "md5",
) -> ChecksumReport:
    manifest_entries = list(manifest_entries or [])
    manifest_index = _build_manifest_index(manifest_entries)
    matched_manifest: set[int] = set()

    entries: list[FileChecksum] = []
    for file_path, root in _iter_input_files(inputs):
        manifest_entry = _match_manifest_entry(
            file_path, root=root, manifest_index=manifest_index
        )
        if manifest_entry:
            matched_manifest.add(id(manifest_entry))

        expected_checksum = _normalise_checksum(
            manifest_entry.checksum if manifest_entry else None, algorithm
        )
        actual_checksum = compute_checksum(file_path, algorithm=algorithm)

        if expected_checksum is None:
            status: ChecksumStatus = "computed"
        elif expected_checksum == actual_checksum.lower():
            status = "ok"
        else:
            status = "mismatch"

        entries.append(
            FileChecksum(
                path=file_path,
                size=file_path.stat().st_size,
                checksum=f"{algorithm}:{actual_checksum}",
                expected_checksum=(
                    f"{algorithm}:{expected_checksum}" if expected_checksum else None
                ),
                status=status,
                manifest=(
                    _serialise_delivery(manifest_entry) if manifest_entry else None
                ),
            )
        )

    missing_entries: list[Mapping[str, object]] = []
    for entry in manifest_entries:
        if id(entry) not in matched_manifest:
            missing_entries.append(_serialise_delivery(entry))

    return ChecksumReport(files=entries, missing_from_manifest=missing_entries)


def _render_text_report(report: ChecksumReport, *, algorithm: str) -> str:
    lines = [f"Checksum report ({algorithm})"]
    summary = report.summary
    lines.append(
        f"Files scanned: {summary['files_scanned']} | "
        f"With manifest: {summary['files_with_manifest']} | "
        f"Mismatches: {summary['mismatched_files']} | "
        f"Missing from manifest: {summary['missing_manifest_entries']}"
    )

    for entry in report.files:
        expected = entry.expected_checksum or "(none)"
        lines.append(
            f"- {entry.path} [{entry.status}] size={entry.size} "
            f"checksum={entry.checksum} expected={expected}"
        )

    if report.missing_from_manifest:
        lines.append("\nManifest entries without files:")
        for missing in report.missing_from_manifest:
            delivery_path = missing.get("delivery_path", "<unknown>")
            lines.append(f"- {delivery_path}")

    return "\n".join(lines)


def _render_report(
    report: ChecksumReport, format: ReportFormat, *, algorithm: str
) -> str:
    if format == "json":
        files = []
        for entry in report.files:
            payload = asdict(entry)
            payload["path"] = str(entry.path)
            files.append(payload)

        payload = {
            "files": files,
            "missing_from_manifest": report.missing_from_manifest,
            "summary": report.summary,
            "algorithm": algorithm,
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    return _render_text_report(report, algorithm=algorithm)


def _load_manifest(manifest: Path | None) -> list[Delivery]:
    if manifest is None:
        return []

    if not manifest.exists() or not manifest.is_file():
        raise typer.BadParameter(
            "Manifest path must point to an existing file", param_hint="manifest"
        )

    try:
        return cast(list[Delivery], load_delivery_manifest(manifest))
    except FileNotFoundError:
        raise typer.BadParameter(
            "Manifest path must point to an existing file", param_hint="manifest"
        ) from None
    except DeliveryManifestError as exc:
        raise OnePieceValidationError(
            f"Unable to parse manifest '{manifest}': {exc}"
        ) from exc


def generate_report(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True),
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help="Optional delivery manifest to compare against discovered files.",
    ),
    algorithm: str = typer.Option(
        "md5",
        "--algorithm",
        "-a",
        help="Checksum algorithm to use (md5 or sha256).",
    ),
    format: ReportFormat = typer.Option(
        "text",
        "--format",
        "-f",
        help="Render the report as text or JSON.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Optional file path for the report. Defaults to stdout when omitted.",
    ),
) -> None:
    """Compute checksums for ingest inputs and emit a report."""

    if not inputs:
        raise OnePieceValidationError("Provide at least one input path")

    algorithm_lower = algorithm.lower()
    if algorithm_lower not in {"md5", "sha256"}:
        raise typer.BadParameter(
            "Checksum algorithm must be 'md5' or 'sha256'", param_hint="algorithm"
        )

    deliveries = _load_manifest(manifest)
    report = build_checksum_report(
        inputs, manifest_entries=deliveries, algorithm=algorithm_lower
    )
    rendered = _render_report(report, format, algorithm=algorithm_lower)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
        typer.echo(f"Report written to {output}")
        return

    typer.echo(rendered)


__all__ = [
    "ChecksumReport",
    "FileChecksum",
    "build_checksum_report",
    "generate_report",
]
