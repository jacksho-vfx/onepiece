from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from apps.onepiece.config import load_profile
from apps.onepiece.utils.errors import OnePieceConfigError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_load_profile_returns_pipeline_metadata(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    user_config = home / ".config" / "onepiece" / "onepiece.toml"
    _write(
        user_config,
        """
[pipelines.render]
display_name = "Render Shots"
queue = "render-farm"

[pipelines.render.parameters]
quality = "high"

[pipelines.ingest]
stages = ["prepare", "transfer"]
""".strip()
        + "\n",
    )

    context = load_profile()

    assert set(context.pipelines) == {"render", "ingest"}
    assert context.pipelines["render"]["display_name"] == "Render Shots"
    assert context.pipelines["render"]["queue"] == "render-farm"
    assert context.pipelines["render"]["parameters"] == {"quality": "high"}
    assert context.pipelines["ingest"]["stages"] == ["prepare", "transfer"]


def test_load_profile_rejects_invalid_pipeline_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    user_config = home / ".config" / "onepiece" / "onepiece.toml"
    _write(
        user_config,
        """
pipelines = "invalid"
""".strip()
        + "\n",
    )

    with pytest.raises(OnePieceConfigError) as excinfo:
        load_profile()

    assert "'pipelines'" in str(excinfo.value)


def test_load_profile_rejects_invalid_pipeline_entry(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    user_config = home / ".config" / "onepiece" / "onepiece.toml"
    _write(
        user_config,
        """
[pipelines]
render = "invalid"
""".strip()
        + "\n",
    )

    with pytest.raises(OnePieceConfigError) as excinfo:
        load_profile()

    assert "Pipeline 'render'" in str(excinfo.value)


def test_load_profile_merges_pipeline_precedence(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    user_config = home / ".config" / "onepiece" / "onepiece.toml"
    _write(
        user_config,
        """
[pipelines.render]
queue = "user-queue"
description = "User Render"

[pipelines.publish]
description = "User Publish"
""".strip()
        + "\n",
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    project_config = project_root / "onepiece.toml"
    _write(
        project_config,
        """
[pipelines.render]
queue = "project-queue"

[pipelines.publish]
description = "Project Publish"
""".strip()
        + "\n",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_config = workspace / "onepiece.toml"
    _write(
        workspace_config,
        """
[pipelines.render]
description = "Workspace Render"

[pipelines.new_pipeline]
description = "Workspace Only"
""".strip()
        + "\n",
    )

    context = load_profile(workspace=workspace, project_root=project_root)

    assert context.sources == (user_config, project_config, workspace_config)
    assert context.pipelines["render"]["queue"] == "project-queue"
    assert context.pipelines["render"]["description"] == "Workspace Render"
    assert context.pipelines["publish"]["description"] == "Project Publish"
    assert context.pipelines["new_pipeline"]["description"] == "Workspace Only"


def test_load_profile_pipeline_customisation_paths(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)

    user_config = home / ".config" / "onepiece" / "onepiece.toml"
    _write(
        user_config,
        """
default_profile = "studio"

[profiles.studio.pipeline]
step_factories = ["studio.pipeline.steps", "custom.steps"]
template_paths = ["~/pipeline/templates", "pipelines/templates"]
""".strip()
        + "\n",
    )

    context = load_profile()

    assert context.pipeline_step_factories == (
        "studio.pipeline.steps",
        "custom.steps",
    )
    assert context.pipeline_template_paths == (
        home / "pipeline" / "templates",
        tmp_path / "pipelines" / "templates",
    )
