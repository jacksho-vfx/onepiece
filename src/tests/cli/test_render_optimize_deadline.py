from pathlib import Path

import pytest
from typer.testing import CliRunner

import apps.onepiece.render.submit.optimize_deadline_command as optimize_command
from apps.onepiece.render.submit.cli import app as render_app
from libraries.automation.render.geometry import GeometryOptimizationResult

runner = CliRunner()


def test_optimize_and_submit_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene = tmp_path / "scene.usd"
    scene.write_text("geometry", encoding="utf-8")
    output = tmp_path / "frames"
    output.mkdir()

    optimized_scene = tmp_path / "optimized" / "scene_optimized.usd"

    def fake_optimise(
        scene_path: Path, output_dir: Path | None = None
    ) -> GeometryOptimizationResult:
        assert scene_path == scene
        assert output_dir is None
        optimized_scene.parent.mkdir(parents=True, exist_ok=True)
        optimized_scene.write_text("optimized geometry", encoding="utf-8")
        return GeometryOptimizationResult(
            source_scene=scene_path,
            optimized_scene=optimized_scene,
            size_before=scene_path.stat().st_size,
            size_after=optimized_scene.stat().st_size,
            operations=("merged duplicate points",),
        )

    submitted: dict[str, str | int | None] = {}

    def fake_submit_job(**kwargs):  # type: ignore[no-untyped-def]
        submitted.update(kwargs)
        return {"job_id": "abc123", "status": "queued", "farm_type": "deadline"}

    monkeypatch.setattr(optimize_command, "optimize_geometry", fake_optimise)
    monkeypatch.setattr(optimize_command, "submit_job", fake_submit_job)

    result = runner.invoke(
        render_app,
        [
            "optimize-deadline",
            "--scene",
            str(scene),
            "--frames",
            "1-5",
            "--output",
            str(output),
            "--priority",
            "60",
            "--chunk-size",
            "2",
            "--pool",
            "farm",
        ],
    )

    assert result.exit_code == 0, result.output
    assert submitted["scene"] == str(optimized_scene)
    assert submitted["chunk_size"] == 2
    assert "Submitted optimised" in result.output


def test_optimize_and_submit_deadline_invalid_frames(tmp_path: Path) -> None:
    scene = tmp_path / "scene.usd"
    scene.write_text("geometry", encoding="utf-8")
    output = tmp_path / "frames"
    output.mkdir()

    result = runner.invoke(
        render_app,
        [
            "optimize-deadline",
            "--scene",
            str(scene),
            "--frames",
            "bad-range",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code != 0
    assert result.exception is not None
    assert "invalid" in str(result.exception).lower()
