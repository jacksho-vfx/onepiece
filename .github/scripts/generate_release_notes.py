from __future__ import annotations

import os
import re
from pathlib import Path


def extract_release_notes(tag: str, changelog: Path) -> str | None:
    if not changelog.exists() or not tag:
        return None

    lines = changelog.read_text(encoding="utf-8").splitlines()
    patterns = [
        rf"^## \[{re.escape(tag)}\]",
        rf"^## \[Desktop {re.escape(tag)}\]",
        rf"^## \[Desktop {re.escape(tag.lstrip('v'))}\]",
    ]

    start_index = None
    for index, line in enumerate(lines):
        if any(re.match(pattern, line) for pattern in patterns):
            start_index = index
            break

    if start_index is None:
        return None

    end_index = None
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith("## "):
            end_index = index
            break

    section = lines[start_index:end_index]
    return "\n".join(section).strip() if section else None


def main() -> None:
    tag = os.environ.get("GITHUB_REF_NAME", "").strip()
    changelog = Path("CHANGELOG.md")
    output = Path("release_notes.md")

    notes = extract_release_notes(tag, changelog)
    if not notes:
        notes = f"## {tag or 'Release'}\n\n- TODO: Add release notes for {tag or 'this release'}."

    output.write_text(f"{notes}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
