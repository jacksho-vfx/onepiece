from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from apps.onepiece.aws.ingest import _prepare_ingest_options
from apps.onepiece.config import load_profile
from apps.onepiece.utils.errors import OnePieceConfigError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_load_profile_merges_precedence(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    user_config = home / ".config" / "onepiece" / "onepiece.toml"
    _write(
        user_config,
        """
default_profile = "user-default"

[profiles.user-default]
project = "UserProject"
show_code = "USR"
vendor_bucket = "user-vendor"
""".strip()
        + "\n",
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    project_config = project_root / "onepiece.toml"
    _write(
        project_config,
        """
default_profile = "project-default"

[profiles.project-default]
project = "Project"
show_code = "PRJ"
vendor_bucket = "project-vendor"

[profiles.user-default]
project = "ProjectUser"
""".strip()
        + "\n",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_config = workspace / "onepiece.toml"
    _write(
        workspace_config,
        """
default_profile = "workspace-default"

[profiles.project-default]
show_code = "WorkspaceShow"
client_bucket = "workspace-client"
""".strip()
        + "\n",
    )

    context = load_profile(
        profile="project-default", workspace=workspace, project_root=project_root
    )

    assert context.name == "project-default"
    assert context.sources == (user_config, project_config, workspace_config)
    assert context.data["project"] == "Project"
    assert context.data["show_code"] == "WorkspaceShow"
    assert context.data["vendor_bucket"] == "project-vendor"
    assert context.data["client_bucket"] == "workspace-client"


def test_load_profile_honours_highest_precedence_default(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    user_config = home / ".config" / "onepiece" / "onepiece.toml"
    _write(
        user_config,
        """
default_profile = "user"

[profiles.user]
project = "User"
show_code = "USR"
""".strip()
        + "\n",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write(
        workspace / "onepiece.toml",
        """
default_profile = "workspace"

[profiles.workspace]
project = "Workspace"
show_code = "WRK"
""".strip()
        + "\n",
    )

    context = load_profile(workspace=workspace)

    assert context.name == "workspace"
    assert context.data["project"] == "Workspace"
    assert context.data["show_code"] == "WRK"


def test_prepare_ingest_options_cli_overrides(tmp_path: Path) -> None:
    profile_data = {
        "project": "ConfigProject",
        "show_code": "CFG",
        "source": "client",
        "vendor_bucket": "cfg-vendor",
        "client_bucket": "cfg-client",
        "ingest": {
            "max_workers": 8,
            "use_asyncio": True,
            "resume": True,
            "checkpoint_dir": str(tmp_path / "checkpoints"),
            "checkpoint_threshold": 1024,
            "upload_chunk_size": 2048,
        },
    }

    resolved = _prepare_ingest_options(
        profile_data,
        project="CLI Project",
        show_code=None,
        source=None,
        vendor_bucket=None,
        client_bucket="cli-client",
        max_workers=2,
        use_asyncio=None,
        resume=None,
        checkpoint_dir=None,
        checkpoint_threshold=None,
        upload_chunk_size=789,
    )

    assert resolved.project == "CLI Project"
    assert resolved.show_code == "CFG"
    assert resolved.source == "client"
    assert resolved.vendor_bucket == "cfg-vendor"
    assert resolved.client_bucket == "cli-client"
    assert resolved.max_workers == 2
    assert resolved.use_asyncio is True
    assert resolved.resume is True
    assert resolved.checkpoint_dir == tmp_path / "checkpoints"
    assert resolved.checkpoint_threshold == 1024
    assert resolved.upload_chunk_size == 789


def test_prepare_ingest_options_requires_project_and_show_code() -> None:
    with pytest.raises(OnePieceConfigError):
        _prepare_ingest_options(
            {},
            project=None,
            show_code="SHOW",
            source=None,
            vendor_bucket=None,
            client_bucket=None,
            max_workers=None,
            use_asyncio=None,
            resume=None,
            checkpoint_dir=None,
            checkpoint_threshold=None,
            upload_chunk_size=None,
        )

    with pytest.raises(OnePieceConfigError):
        _prepare_ingest_options(
            {"project": "Project"},
            project=None,
            show_code=None,
            source=None,
            vendor_bucket=None,
            client_bucket=None,
            max_workers=None,
            use_asyncio=None,
            resume=None,
            checkpoint_dir=None,
            checkpoint_threshold=None,
            upload_chunk_size=None,
        )


def test_load_profile_expands_project_root_env_var(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project_root = home / "project"
    workspace = tmp_path / "workspace"

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("ONEPIECE_PROJECT_ROOT", "~/project")

    project_config = project_root / "onepiece.toml"
    _write(
        project_config,
        """
default_profile = "project"

[profiles.project]
project = "Project"
""".strip()
        + "\n",
    )

    workspace.mkdir()

    context = load_profile(workspace=workspace)

    assert context.name == "project"
    assert project_config in context.sources
    assert context.data["project"] == "Project"
