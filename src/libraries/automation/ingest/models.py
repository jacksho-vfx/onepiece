"""Dataclasses describing ingestable media and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libraries.automation.ingest import Delivery


def _format_shot_name(episode: str, scene: str, shot: str) -> str:
    return f"{episode}_{scene}_{shot}"


@dataclass(frozen=True)
class MediaInfo:
    """Metadata parsed from a delivery filename."""

    show_code: str
    episode: str
    scene: str
    shot: str
    descriptor: str
    extension: str

    @property
    def shot_name(self) -> str:
        return _format_shot_name(self.episode, self.scene, self.shot)

    @property
    def version_code(self) -> str:
        """Return a stable code suitable for ShotGrid Version entities."""

        descriptor = f"_{self.descriptor}" if self.descriptor else ""
        return f"{self.shot_name}{descriptor}"


@dataclass
class IngestedMedia:
    """Description of a successfully processed media file."""

    path: Path
    bucket: str
    key: str
    media_info: MediaInfo
    delivery: Delivery | None = None
    skipped: bool = False


@dataclass
class IngestReport:
    """Summary of an ingest run."""

    processed: list[IngestedMedia] = field(default_factory=list)
    invalid: list[tuple[Path, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def processed_count(self) -> int:
        return len(self.processed)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid)


__all__ = ["MediaInfo", "IngestedMedia", "IngestReport", "_format_shot_name"]
