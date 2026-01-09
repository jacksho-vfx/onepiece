from __future__ import annotations

from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from libraries.pipeline.registry import (
    load_pipeline_templates_from_paths,
    load_step_factories_from_modules,
)


def test_load_step_factories_from_modules(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    module_path = tmp_path / "studio_steps.py"
    module_path.write_text(
        """
from libraries.pipeline.models import PipelineStep

def custom_step_factory(config):
    return PipelineStep(name=config.get("name", "custom"), provider=lambda: None)

def pipeline_step_factories():
    return {"studio.custom": custom_step_factory}
""".strip()
        + "\n"
    )

    monkeypatch.syspath_prepend(tmp_path)

    factories = load_step_factories_from_modules(["studio_steps"])

    assert "studio.custom" in factories
    assert callable(factories["studio.custom"])


def test_load_pipeline_templates_from_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "archvis.toml"
    manifest.write_text(
        """
name = "archvis-review"
summary = "Archvis review publish."

[[steps]]
id = "noop"
uses = "noop"
""".strip()
        + "\n"
    )

    templates = load_pipeline_templates_from_paths([manifest])

    assert templates[0].name == "archvis"
    assert templates[0].summary == "Archvis review publish."
    assert templates[0].manifest["name"] == "archvis-review"
