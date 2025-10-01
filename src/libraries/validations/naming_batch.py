import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

from libraries.validations import naming


_SEQ_SHOT_PATTERN = re.compile(r"^seq\d{3}_sh\d{3}$", re.IGNORECASE)
_SEQ_ASSET_PATTERN = re.compile(
    r"^seq\d{3}_sh\d{3}_[a-z0-9]+(?:_[a-z0-9]+)*_v\d{3}$", re.IGNORECASE
)


@dataclass(frozen=True)
class NameValidationResult:
    """Structured response describing a naming validation result."""

    name: str
    valid: bool
    detail: str


def validate_names_in_csv(csv_path: Path) -> List[NameValidationResult]:
    """
    Validate naming patterns for every 'name' column entry in a CSV.
    Returns list of structured results.
    """

    results: List[NameValidationResult] = []
    with csv_path.open(newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        if reader.fieldnames is None or "name" not in reader.fieldnames:
            raise ValueError("CSV must have a 'name' column.")
        for row in reader:
            name = row["name"].strip()
            results.append(NameValidationResult(name, *_validate_single_name(name)))
    return results


def validate_names_in_dir(directory: Path) -> List[NameValidationResult]:
    """Validate each filename (without extension) in a directory."""

    results: List[NameValidationResult] = []
    for file in directory.iterdir():
        if file.is_file():
            name = file.stem
            results.append(NameValidationResult(name, *_validate_single_name(name)))
    return results


def _validate_single_name(name: str) -> tuple[bool, str]:
    """Core validation for a single name string."""

    if naming.validate_asset_name(name):
        return True, "asset(ep/scene shot)"
    if _SEQ_ASSET_PATTERN.match(name):
        return True, "asset(sequence shot)"
    if naming.validate_shot_name(name):
        return True, "shot(ep/scene)"
    if _SEQ_SHOT_PATTERN.match(name):
        return True, "shot(sequence)"
    if naming.validate_shot(name):
        return True, "shot(number)"
    if naming.validate_scene_name(name):
        return True, "scene"
    if naming.validate_episode_name(name):
        return True, "episode"
    if naming.validate_show_name(name):
        return True, "show"
    return False, "invalid pattern"


__all__ = [
    "NameValidationResult",
    "validate_names_in_csv",
    "validate_names_in_dir",
]
