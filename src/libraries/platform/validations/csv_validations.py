import csv
import re
from pathlib import Path
from typing import List
import structlog

log = structlog.get_logger(__name__)


def validate_shots_csv(csv_path: Path) -> List[str]:
    """
    Validate and parse a CSV of shot codes.

    Requirements:
      * File exists and is readable.
      * At least one header starts with 'shot' (case-insensitive).
      * Each row in that column is non-empty.
      * Each code matches E##[_-]S##[_-]SH### pattern.

    Returns:
      A list of validated shot codes.

    Raises:
      ValueError if any validation step fails.
    """
    if not csv_path.exists() or not csv_path.is_file():
        raise ValueError(f"CSV file not found: {csv_path}")

    shot_codes: List[str] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row.")

        possible_cols = [c for c in reader.fieldnames if c.lower().startswith("shot")]
        if not possible_cols:
            raise ValueError("CSV must contain a column whose name starts with 'shot'.")

        col = possible_cols[0]
        pattern = re.compile(r"^E\d+[_-]S\d+[_-]SH\d+$", re.I)

        for line_num, row in enumerate(reader, start=2):
            val = (row.get(col) or "").strip()
            if not val:
                raise ValueError(
                    f"Empty shot code in column '{col}' at line {line_num}."
                )
            if not pattern.match(val):
                raise ValueError(
                    f"Invalid shot code format '{val}' at line {line_num}."
                )
            shot_codes.append(val)

    if not shot_codes:
        raise ValueError("No valid shot codes found in CSV.")

    log.info("validate_shots_csv_success", csv=str(csv_path), count=len(shot_codes))
    return shot_codes
