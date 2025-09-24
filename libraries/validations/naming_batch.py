import csv
from pathlib import Path
from typing import List, Tuple
import structlog

from onepiece.validations.naming_conventions import (
    validate_show_name,
    validate_episode_name,
    validate_scene_name,
    validate_shot,
    validate_shot_name,
    validate_asset_name,
)

log = structlog.get_logger(__name__)


def validate_names_in_csv(csv_path: Path) -> List[Tuple[str, bool, str]]:
    """
    Validate naming patterns for every 'name' column entry in a CSV.
    Returns list of (name, valid, reason).
    """
    results: List[Tuple[str, bool, str]] = []
    with csv_path.open(newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        if "name" not in reader.fieldnames:
            raise ValueError("CSV must have a 'name' column.")
        for row in reader:
            name = row["name"].strip()
            valid, reason = _validate_single_name(name)
            results.append((name, valid, reason))
    return results


def validate_names_in_dir(directory: Path) -> List[Tuple[str, bool, str]]:
    """
    Validate each filename (without extension) in a directory.
    """
    results: List[Tuple[str, bool, str]] = []
    for file in directory.iterdir():
        if file.is_file():
            name = file.stem
            valid, reason = _validate_single_name(name)
            results.append((name, valid, reason))
    return results


def _validate_single_name(name: str) -> Tuple[bool, str]:
    """
    Core validation for a single name string.
    """
    if validate_asset_name(name):
        return True, "asset"
    if validate_shot_name(name):
        return True, "shot"
    parts = name.split("_")
    if len(parts) == 1 and validate_show_name(parts[0]):
        return True, "show"
    return False, "invalid pattern"
