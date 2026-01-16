"""Render submission CLI package."""

from typing import Any

from ..jobs import RenderJobClient, RenderJobClientError
from . import cancel_command as _cancel_command
from . import status_command as _status_command
from . import submit_command as _submit_command
from .cli import app, presets_app
from .helpers import (
    DCC_CHOICES,
    FARM_ADAPTERS,
    FARM_CAPABILITY_PROVIDERS,
    FARM_CHOICES,
    coerce_text,
    extract_history,
    fetch_adapter_capabilities,
    get_adapter,
    get_adapter_capabilities,
    parse_frame_count,
    refresh_capabilities_cache,
    resolve_metrics,
    resolve_priority_and_chunk_size,
)
from .scripts import (
    RenderScriptBundle,
    build_render_script_bundle,
    optimisation_preview,
    run_render_submission,
    sanity_check_submission,
    write_render_script_bundle,
)
from .submit_command import log as log

__all__ = [
    "DCC_CHOICES",
    "FARM_ADAPTERS",
    "FARM_CAPABILITY_PROVIDERS",
    "FARM_CHOICES",
    "app",
    "RenderJobClient",
    "RenderJobClientError",
    "RenderScriptBundle",
    "coerce_text",
    "extract_history",
    "fetch_adapter_capabilities",
    "get_adapter",
    "get_adapter_capabilities",
    "log",
    "parse_frame_count",
    "presets_app",
    "build_render_script_bundle",
    "optimisation_preview",
    "run_render_submission",
    "refresh_capabilities_cache",
    "sanity_check_submission",
    "resolve_metrics",
    "resolve_priority_and_chunk_size",
    "write_render_script_bundle",
]

_refresh_capabilities_cache = refresh_capabilities_cache
_get_adapter_capabilities = get_adapter_capabilities
_get_adapter = get_adapter
_parse_frame_count = parse_frame_count
_resolve_metrics = resolve_metrics
_resolve_priority_and_chunk_size = resolve_priority_and_chunk_size


def __getattr__(name: str) -> Any:
    if name == "log":
        return _submit_command.log
    if hasattr(_submit_command, name):
        return getattr(_submit_command, name)
    if hasattr(_status_command, name):
        return getattr(_status_command, name)
    if hasattr(_cancel_command, name):
        return getattr(_cancel_command, name)
    raise AttributeError(name)


def __setattr__(name: str, value: Any) -> None:
    if name == "log":
        _submit_command.log = value
    globals()[name] = value
