"""Post-ingest hook definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class IngestContext:
    asset_id: str
    asset_dir: Path
    metadata_path: Path
    project_root: Path


class IngestHook(Protocol):
    name: str

    def run(self, context: IngestContext, config: dict[str, Any]) -> None:
        """Execute the hook for the ingest context."""


HookRegistry = dict[str, IngestHook]

_HOOK_REGISTRY: HookRegistry = {}


def register_hook(hook: IngestHook) -> None:
    _HOOK_REGISTRY[hook.name] = hook


def get_hook(name: str) -> IngestHook | None:
    return _HOOK_REGISTRY.get(name)


@dataclass(frozen=True)
class HookExecution:
    name: str
    timestamp: str


def load_hook_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    import json

    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def save_hook_state(path: Path, entries: dict[str, str]) -> None:
    import json

    path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")


def run_hooks(context: IngestContext, hook_configs: list[dict[str, Any]]) -> None:
    state_path = context.asset_dir / "hooks.json"
    hook_state = load_hook_state(state_path)
    for hook_config in hook_configs:
        name = hook_config["name"]
        if name in hook_state:
            continue
        hook = get_hook(name)
        if hook is None:
            raise ValueError(f"Hook '{name}' is not registered")
        hook.run(context, hook_config.get("config", {}))
        hook_state[name] = datetime_now()
        save_hook_state(state_path, hook_state)


def datetime_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class S5ToAwsSyncHook:
    name = "s5_aws_sync"

    def run(self, context: IngestContext, config: dict[str, Any]) -> None:
        import subprocess

        source_template = str(config.get("source", context.asset_dir))
        source = source_template.format(asset_dir=context.asset_dir)
        destination = config.get("destination")
        if not destination:
            raise ValueError("s5_aws_sync hook requires a destination")
        args = ["aws", "s3", "sync", source, str(destination)]
        env = None
        if "aws_profile" in config:
            import os

            extra_env = config.get("env", {})
            env = dict(os.environ)
            if isinstance(extra_env, dict):
                env.update({str(key): str(value) for key, value in extra_env.items()})
            env["AWS_PROFILE"] = str(config["aws_profile"])
        subprocess.run(args, check=True, env=env)


register_hook(S5ToAwsSyncHook())
