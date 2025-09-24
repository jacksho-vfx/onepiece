import json
from pathlib import Path

from typer.testing import CliRunner

from apps.onepiece.app import app
from onepiece.dcc.dcc_client import SupportedDCC


runner = CliRunner()


def test_publish_cli_invokes_publish(monkeypatch, tmp_path):
    renders = tmp_path / "renders"
    renders.mkdir()
    (renders / "beauty.exr").write_text("beauty")

    previews = tmp_path / "previews"
    previews.mkdir()
    (previews / "preview.jpg").write_text("preview")

    otio = tmp_path / "edit.otio"
    otio.write_text("otio")

    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"shot": "010"}))

    destination = tmp_path / "package"
    destination.mkdir()

    called = {}

    def fake_publish_scene(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs
        return Path("/tmp/package")

    monkeypatch.setattr(
        "apps.onepiece.dcc.publish.publish_scene", fake_publish_scene
    )

    result = runner.invoke(
        app,
        [
            "publish",
            "--dcc",
            "Nuke",
            "--scene-name",
            "ep01_sh010",
            "--renders",
            str(renders),
            "--previews",
            str(previews),
            "--otio",
            str(otio),
            "--metadata",
            str(metadata),
            "--destination",
            str(destination),
            "--bucket",
            "bucket",
            "--show-code",
            "OP",
            "--show-type",
            "vfx",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called["args"][0] is SupportedDCC.NUKE
    assert called["kwargs"]["scene_name"] == "ep01_sh010"
    assert called["kwargs"]["show_type"] == "vfx"
