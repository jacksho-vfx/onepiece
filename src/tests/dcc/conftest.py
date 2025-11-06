from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


PublishInputs = tuple[Path, Path, Path, dict[str, Any], Path]


@pytest.fixture
def publish_inputs(tmp_path: Path) -> PublishInputs:
    renders = tmp_path / "renders"
    renders.mkdir()
    (renders / "beauty.exr").write_text("beauty")

    previews = tmp_path / "previews"
    previews.mkdir()
    (previews / "preview.jpg").write_text("preview")

    otio = tmp_path / "edit.otio"
    otio.write_text("otio data")

    metadata: dict[str, Any] = {"shot": "010"}

    destination = tmp_path / "published"

    return renders, previews, otio, metadata, destination
