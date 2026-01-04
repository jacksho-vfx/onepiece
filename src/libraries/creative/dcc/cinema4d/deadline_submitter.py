"""Cinema 4D dialog for submitting renders to a Deadline farm."""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import structlog

from libraries.automation.render import deadline
from libraries.automation.render.base import (
    AdapterCapabilities,
    RenderAdapterError,
    RenderSubmissionError,
)
from libraries.automation.render.config import get_adapter_setting

try:  # pragma: no cover - Cinema 4D is not available in CI
    import c4d  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - replaced by tests stubs
    c4d = None  # type: ignore

from .metadata import load_cinema4d_summary


def _show_message(module: object | None, message: str) -> None:
    gui_module = getattr(module, "gui", None) if module is not None else None
    message_dialog = getattr(gui_module, "MessageDialog", None)
    if callable(message_dialog):
        message_dialog(message)
    else:  # pragma: no cover - fall back to stdout when GUI is unavailable
        print(message)


log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeadlineSubmitterDefaults:
    """Default values used to pre-populate the Deadline submitter."""

    scene: str
    frames: str
    output: str
    priority: int
    user: str
    chunk_size: int | None
    pool: str | None


def _active_scene_path(module: object | None) -> str:
    documents = getattr(module, "documents", None)
    get_active_document = getattr(documents, "GetActiveDocument", None)
    if not callable(get_active_document):
        return ""

    doc = get_active_document()
    if doc is None:
        return ""

    doc_dir = getattr(doc, "GetDocumentPath", lambda: "")() or ""
    doc_name = getattr(doc, "GetDocumentName", lambda: "")() or ""
    if doc_dir and doc_name:
        return str(Path(doc_dir) / doc_name)
    return doc_name


def _default_frames(env: Mapping[str, str]) -> str:
    summary = load_cinema4d_summary(env=env)
    frame_range = None
    if summary:
        frame_range = summary.get("frame_range")

    if isinstance(frame_range, (list, tuple)) and len(frame_range) == 2:
        start, end = frame_range
        if start is not None and end is not None:
            return f"{int(start)}-{int(end)}"

    return "1-100"


def _default_output(scene_path: str) -> str:
    if not scene_path:
        return ""

    scene = Path(scene_path)
    destination = scene.with_suffix("")
    return str(destination) + "_render"


def _default_priority(capabilities: AdapterCapabilities, env: Mapping[str, str]) -> int:
    env_priority = env.get("RENDER_DEADLINE_PRIORITY") or get_adapter_setting(
        "deadline", "priority"
    )
    if env_priority:
        try:
            return int(env_priority)
        except ValueError:
            log.warning("deadline.submitter.priority_invalid", value=env_priority)

    return int(capabilities.get("default_priority", 50))


def _default_chunk_size(
    capabilities: AdapterCapabilities, env: Mapping[str, str]
) -> int | None:
    if not capabilities.get("chunk_size_enabled", True):
        return None

    env_chunk = env.get("RENDER_DEADLINE_CHUNK_SIZE") or get_adapter_setting(
        "deadline", "chunk_size"
    )
    if env_chunk:
        try:
            return int(env_chunk)
        except ValueError:
            log.warning("deadline.submitter.chunk_size_invalid", value=env_chunk)

    if "default_chunk_size" in capabilities:
        return int(capabilities["default_chunk_size"])

    return None


def _default_pool(env: Mapping[str, str]) -> str | None:
    pool = env.get("RENDER_DEADLINE_POOL") or get_adapter_setting("deadline", "pool")
    return pool if pool else None


def build_default_settings(
    *,
    module: object | None = None,
    env: Mapping[str, str] | None = None,
    capabilities: AdapterCapabilities | None = None,
) -> DeadlineSubmitterDefaults:
    """Return defaults for the Deadline submitter dialog."""

    env_mapping = env or os.environ
    capability_data = capabilities or deadline.get_capabilities()

    scene = _active_scene_path(module)
    frames = _default_frames(env_mapping)
    output = _default_output(scene)
    priority = _default_priority(capability_data, env_mapping)
    user = env_mapping.get("USER") or env_mapping.get("USERNAME") or getpass.getuser()
    chunk_size = _default_chunk_size(capability_data, env_mapping)
    pool = _default_pool(env_mapping)

    return DeadlineSubmitterDefaults(
        scene=scene,
        frames=frames,
        output=output,
        priority=priority,
        user=user,
        chunk_size=chunk_size,
        pool=pool,
    )


class DeadlineSubmitterDialog:
    """Build a Cinema 4D dialog for submitting Deadline jobs."""

    ID_FRAME_RANGE = 2001
    ID_OUTPUT_PATH = 2002
    ID_PRIORITY = 2003
    ID_CHUNK_SIZE = 2004
    ID_POOL = 2005
    ID_ADVANCED_TOGGLE = 2006
    ID_SUBMIT_BUTTON = 2007
    ID_USER = 2008
    ID_CHUNK_LABEL = 2009
    ID_POOL_LABEL = 2010

    def __init__(
        self,
        *,
        module: object | None = None,
        defaults: DeadlineSubmitterDefaults | None = None,
        capabilities: AdapterCapabilities | None = None,
        submit_job: Callable[..., Any] = deadline.submit_job,
    ) -> None:
        self._module = module or c4d
        if self._module is None:
            raise RuntimeError(
                "Cinema 4D Python API is unavailable; cannot build submitter"
            )

        gui_module = getattr(self._module, "gui", None)
        dialog_type = getattr(gui_module, "GeDialog", None)
        if dialog_type is None:
            raise RuntimeError(
                "Cinema 4D GUI module is unavailable; cannot build submitter"
            )

        self._defaults = defaults or build_default_settings(
            module=self._module, capabilities=capabilities
        )
        self._capabilities = capabilities or deadline.get_capabilities()
        self._submit_job = submit_job
        self._advanced_visible = False
        self._dialog = dialog_type()

        self._dialog.CreateLayout = self.CreateLayout  # type: ignore[assignment]
        self._dialog.Command = self.Command  # type: ignore[assignment]

    def open(self) -> Any:
        dialog_type = getattr(self._module, "DLG_TYPE_ASYNC", 1)
        self._dialog.Open(dialog_type, pluginid=1060002, defaultw=480, defaulth=0)
        return self._dialog

    # Cinema 4D expects CreateLayout to return True on success.
    def CreateLayout(self) -> bool:  # pragma: no cover - executed via tests stubs
        self._dialog.SetTitle("Deadline Submitter")

        self._dialog.AddStaticText(1000, 0, 0, 0, "Scene")
        self._dialog.AddStaticText(1001, 0, 0, 0, self._defaults.scene or "<unsaved>")

        self._dialog.AddStaticText(1002, 0, 0, 0, "Frame Range")
        self._dialog.AddEditText(self.ID_FRAME_RANGE, 0, 0, 0)
        self._dialog.SetString(self.ID_FRAME_RANGE, self._defaults.frames)

        self._dialog.AddStaticText(1003, 0, 0, 0, "Output")
        self._dialog.AddEditText(self.ID_OUTPUT_PATH, 0, 0, 0)
        self._dialog.SetString(self.ID_OUTPUT_PATH, self._defaults.output)

        self._dialog.AddStaticText(1004, 0, 0, 0, "User")
        self._dialog.AddEditText(self.ID_USER, 0, 0, 0)
        self._dialog.SetString(self.ID_USER, self._defaults.user)

        self._dialog.AddStaticText(1005, 0, 0, 0, "Priority")
        self._dialog.AddEditText(self.ID_PRIORITY, 0, 0, 0)
        self._dialog.SetInt32(self.ID_PRIORITY, int(self._defaults.priority))

        self._dialog.AddCheckbox(
            self.ID_ADVANCED_TOGGLE, 0, 0, 0, "Show advanced settings"
        )
        self._dialog.SetBool(self.ID_ADVANCED_TOGGLE, False)

        self._dialog.AddStaticText(self.ID_CHUNK_LABEL, 0, 0, 0, "Chunk Size")
        self._dialog.AddEditText(self.ID_CHUNK_SIZE, 0, 0, 0)
        if self._defaults.chunk_size is not None:
            self._dialog.SetInt32(self.ID_CHUNK_SIZE, int(self._defaults.chunk_size))
        self._dialog.AddStaticText(self.ID_POOL_LABEL, 0, 0, 0, "Pool")
        self._dialog.AddEditText(self.ID_POOL, 0, 0, 0)
        if self._defaults.pool:
            self._dialog.SetString(self.ID_POOL, self._defaults.pool)

        self._dialog.AddButton(self.ID_SUBMIT_BUTTON, 0, 0, 0, "Submit to Deadline")

        self._update_advanced_visibility()
        return True

    def Command(self, message_id: int, msg: object | None) -> bool:
        if message_id == self.ID_ADVANCED_TOGGLE:
            self._advanced_visible = not self._advanced_visible
            self._update_advanced_visibility()
            return True

        if message_id == self.ID_SUBMIT_BUTTON:
            self._submit()
            return True

        return False

    def _update_advanced_visibility(self) -> None:
        hidden = not self._advanced_visible
        hide = getattr(self._dialog, "HideElement", None)
        if callable(hide):
            hide(self.ID_CHUNK_LABEL, hidden)
            hide(self.ID_CHUNK_SIZE, hidden)
            hide(self.ID_POOL_LABEL, hidden)
            hide(self.ID_POOL, hidden)

    def _submit(self) -> None:
        frames = self._dialog.GetString(self.ID_FRAME_RANGE)
        output = self._dialog.GetString(self.ID_OUTPUT_PATH)
        priority = self._dialog.GetInt32(self.ID_PRIORITY)
        user = self._dialog.GetString(self.ID_USER)

        chunk_size = None
        if self._advanced_visible and self._capabilities.get(
            "chunk_size_enabled", True
        ):
            chunk_size = self._dialog.GetInt32(self.ID_CHUNK_SIZE)

        pool = None
        if self._advanced_visible:
            pool_value = self._dialog.GetString(self.ID_POOL)
            pool = pool_value or None

        try:
            result = self._submit_job(
                scene=self._defaults.scene,
                frames=frames or self._defaults.frames,
                output=output or self._defaults.output,
                dcc="cinema4d",
                priority=int(priority),
                user=user or self._defaults.user,
                chunk_size=chunk_size,
                pool=pool,
            )
        except (RenderSubmissionError, RenderAdapterError) as exc:
            _show_message(self._module, f"Deadline submission failed: {exc}")
            return

        message = f"Submitted to Deadline (job {result.get('job_id', 'unknown')})."
        if pool:
            message += f" Pool: {pool}."
        _show_message(self._module, message)


def launch_deadline_submitter(
    *,
    module: object | None = None,
    defaults: DeadlineSubmitterDefaults | None = None,
    capabilities: AdapterCapabilities | None = None,
    submit_job: Callable[..., Any] = deadline.submit_job,
) -> DeadlineSubmitterDialog:
    """Create and display the Deadline submitter dialog."""

    dialog = DeadlineSubmitterDialog(
        module=module,
        defaults=defaults,
        capabilities=capabilities,
        submit_job=submit_job,
    )
    dialog.open()
    return dialog


__all__ = [
    "DeadlineSubmitterDefaults",
    "DeadlineSubmitterDialog",
    "build_default_settings",
    "launch_deadline_submitter",
]
