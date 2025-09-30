"""Utilities for building ffmpeg concat commands."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

__all__ = [
    "BurnInMetadata",
    "build_burnin_filter",
    "create_concat_file",
    "run_ffmpeg_concat",
]


@dataclass
class BurnInMetadata:
    """Metadata shown as on-screen burn-ins."""

    shot: str
    version: str
    frame_range: str
    user: str


def create_concat_file(sources: Sequence[str], directory: Path) -> Path:
    """Write an ffmpeg concat list file for the provided sources."""

    directory.mkdir(parents=True, exist_ok=True)
    concat_path = directory / "concat.txt"
    lines: list[str] = []
    for source in sources:
        safe_source = str(source).replace("'", "'\\''")
        lines.append(f"file '{safe_source}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat_path


def build_burnin_filter(burnins: Sequence[BurnInMetadata]) -> str:
    """Return a filter_complex string that overlays simple text burn-ins."""

    if not burnins:
        return ""

    overlays: list[str] = []
    for burnin in burnins:
        text = (
            f"Shot: {burnin.shot} | Version: {burnin.version} | "
            f"Frames: {burnin.frame_range} | User: {burnin.user}"
        )
        escaped = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        overlays.append(
            "drawtext=text='"
            f"{escaped}'"
            ":x=24:y=24:fontsize=24:fontcolor=white:"
            "box=1:boxcolor=black@0.6"
        )
    return ",".join(overlays)


def run_ffmpeg_concat(
    concat_file: Path,
    output: Path,
    *,
    codec: str,
    burnins: Sequence[BurnInMetadata] | None = None,
) -> subprocess.CompletedProcess:
    """Execute ffmpeg to concatenate clips into a single movie."""

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
    ]

    filter_expr = build_burnin_filter(burnins or [])
    if filter_expr:
        command.extend(["-vf", filter_expr])

    command.extend(["-c:v", codec, str(output)])

    return subprocess.run(command, check=True, capture_output=True, text=True)
