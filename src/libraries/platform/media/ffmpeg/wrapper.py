"""Utilities for building ffmpeg concat commands."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Any

__all__ = [
    "BurnInMetadata",
    "BurnInOptions",
    "build_burnin_filter",
    "create_concat_file",
    "run_ffmpeg_concat",
]


@dataclass
class BurnInMetadata:
    """Metadata shown as on-screen burn-ins."""

    show: str
    shot: str
    version: str
    date: str
    frame_range: str
    user: str


@dataclass(slots=True)
class BurnInOptions:
    """Display settings for burn-in overlays."""

    fontfile: str | None = None
    fontcolor: str = "white"
    boxcolor: str = "black@0.6"
    fontsize: int = 24
    margin: int = 24
    slate_position: str = "top-left"
    counter_position: str = "bottom-right"
    frame_rate: float = 24.0


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


def _escape_drawtext_value(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("\n", "\\n")
    )


def _position_expr(position: str, margin: int, offset: int = 0) -> tuple[str, str]:
    x_expr = f"{margin}"
    y_expr = f"{offset}"

    if position.endswith("right"):
        x_expr = f"w-tw-{margin}"
    if position.startswith("bottom"):
        y_expr = f"h-th-{offset}"

    return x_expr, y_expr


def _slate_offset(options: BurnInOptions, block_height: int, index: int) -> int:
    return options.margin + index * (block_height + max(4, options.margin // 2))


def build_burnin_filter(
    burnins: Sequence[BurnInMetadata], *, options: BurnInOptions | None = None
) -> str:
    """Return a filter_complex string that overlays simple text burn-ins."""

    if not burnins:
        return ""

    settings = options or BurnInOptions()
    overlays: list[str] = []

    slate_fields = ("show", "shot", "version", "user", "date", "frame_range")
    slate_lines = len(slate_fields)
    block_height = settings.fontsize * slate_lines + 4 * (slate_lines - 1)

    for idx, burnin in enumerate(burnins):
        text_lines = [
            f"Show: {burnin.show}",
            f"Shot: {burnin.shot}",
            f"Version: {burnin.version}",
            f"User: {burnin.user}",
            f"Date: {burnin.date}",
            f"Frames: {burnin.frame_range}",
        ]
        text = "\n".join(text_lines)
        escaped = _escape_drawtext_value(text)
        y_offset = _slate_offset(settings, block_height, idx)
        x_expr, y_expr = _position_expr(
            settings.slate_position, settings.margin, y_offset
        )
        overlay = (
            "drawtext="
            f"text='{escaped}'"
            f":x={x_expr}:"
            f"y={y_expr}:"
            f"fontsize={settings.fontsize}:"
            f"fontcolor={settings.fontcolor}:"
            "box=1:"
            f"boxcolor={settings.boxcolor}:"
            "line_spacing=4"
        )
        if settings.fontfile:
            overlay += f":fontfile='{_escape_drawtext_value(settings.fontfile)}'"
        overlays.append(overlay)

    timecode_offset = settings.margin
    x_expr, y_expr = _position_expr(
        settings.counter_position, settings.margin, timecode_offset
    )
    timecode_overlay = (
        "drawtext="
        "timecode='00\\:00\\:00\\:00':"
        f"r={settings.frame_rate}:"
        f"x={x_expr}:"
        f"y={y_expr}:"
        f"fontsize={settings.fontsize}:"
        f"fontcolor={settings.fontcolor}:"
        "box=1:"
        f"boxcolor={settings.boxcolor}"
    )
    if settings.fontfile:
        timecode_overlay += f":fontfile='{_escape_drawtext_value(settings.fontfile)}'"
    overlays.append(timecode_overlay)

    frame_offset = settings.margin + settings.fontsize + 8
    x_expr, y_expr = _position_expr(
        settings.counter_position, settings.margin, frame_offset
    )
    frame_counter_overlay = (
        "drawtext="
        "text='Frame %{n}':"
        f"x={x_expr}:"
        f"y={y_expr}:"
        f"fontsize={settings.fontsize}:"
        f"fontcolor={settings.fontcolor}:"
        "box=1:"
        f"boxcolor={settings.boxcolor}"
    )
    if settings.fontfile:
        frame_counter_overlay += (
            f":fontfile='{_escape_drawtext_value(settings.fontfile)}'"
        )
    overlays.append(frame_counter_overlay)

    return ",".join(overlays)


def run_ffmpeg_concat(
    concat_file: Path,
    output: Path,
    *,
    codec: str,
    burnins: Sequence[BurnInMetadata] | None = None,
    burnin_options: BurnInOptions | None = None,
) -> subprocess.CompletedProcess[Any]:
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

    filter_expr = build_burnin_filter(burnins or [], options=burnin_options)
    if filter_expr:
        command.extend(["-vf", filter_expr])

    command.extend(["-c:v", codec, str(output)])

    return subprocess.run(command, check=True, capture_output=True, text=True)
