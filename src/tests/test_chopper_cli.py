from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from apps.chopper.app import app


def test_render_reports_invalid_scene_file(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    # Missing the required "frames" key to trigger a validation failure.
    scene_path.write_text(
        json.dumps({"width": 16, "height": 12}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, [str(scene_path)])

    assert result.exit_code == 2
    assert "Usage: render" in result.stderr
