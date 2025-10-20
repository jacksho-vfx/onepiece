"""Maya specific DCC helpers."""

from __future__ import annotations

import sys
import types

# --------------------------------------------------------------------------- #
# Safe import guard for environments without Maya / PyMEL
# --------------------------------------------------------------------------- #
try:
    import pymel.core  # noqa: F401
except ModuleNotFoundError:
    # Create lightweight dummy modules so downstream imports succeed
    stub = types.ModuleType("maya")
    sys.modules.setdefault("maya", stub)
    sys.modules.setdefault("maya.cmds", types.ModuleType("maya.cmds"))
    sys.modules.setdefault("maya.utils", types.ModuleType("maya.utils"))
    sys.modules.setdefault("pymel", types.ModuleType("pymel"))
    core_module = sys.modules.setdefault("pymel.core", types.ModuleType("pymel.core"))
    sys.modules.setdefault("pymel.core.system", types.ModuleType("pymel.core.system"))
    sys.modules.setdefault("pymel.core.general", types.ModuleType("pymel.core.general"))

    def _missing_pymel_callable(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(
            "PyMEL (pymel.core) is unavailable outside of Autodesk Maya."
        )

    for name in (
        "listReferences",
        "namespaceInfo",
        "listNamespaces",
        "namespace",
        "ls",
        "delete",
    ):
        setattr(core_module, name, _missing_pymel_callable)

# --------------------------------------------------------------------------- #
# Import public submodules (these can now import safely)
# --------------------------------------------------------------------------- #
from .batch_exporter import (  # noqa: F401
    DEFAULT_EXPORT_SETTINGS,
    BatchExportItem,
    BatchExportResult,
    BatchExporter,
    ExportFormat,
    ExportRecord,
)
from .character_selector import (  # noqa: F401
    CharacterSelectorPanel,
    RigDescriptor,
    discover_rigs,
)
from .batch_retargeting import (  # noqa: F401
    BatchRetargetingTool,
    RetargetError,
    RetargetMapping,
    RetargetResult,
)
from .auto_rig_validator import (  # noqa: F401
    DEFAULT_CONTROL_PREFIXES,
    DEFAULT_JOINT_PREFIXES,
    DEFAULT_REQUIRED_CONTROL_ATTRIBUTES,
    DEFAULT_REQUIRED_HIERARCHY,
    RigValidationIssue,
    RigValidationReport,
    validate_rig_import,
)
from .playblast_tool import (  # noqa: F401
    PlayblastAutomationTool,
    PlayblastRequest,
    PlayblastResult,
    ReviewUploader,
    build_playblast_filename,
)
from .animation_debugger import (  # noqa: F401
    AnimationDebuggerIssue,
    AnimationDebuggerReport,
    CacheLinkInfo,
    ConstraintInfo,
    FrameRangeInfo,
    debug_animation,
)
from .unreal_export_checker import (  # noqa: F401
    DEFAULT_ALLOWED_PREFIXES,
    DEFAULT_EXPECTED_ROOT,
    DEFAULT_EXPECTED_SCALE,
    DEFAULT_REQUIRED_JOINTS,
    DEFAULT_SCALE_TOLERANCE,
    UnrealExportIssue,
    UnrealExportReport,
    validate_unreal_export,
)

__all__ = [
    "DEFAULT_EXPORT_SETTINGS",
    "BatchExportItem",
    "BatchExportResult",
    "BatchExporter",
    "ExportFormat",
    "ExportRecord",
    "CharacterSelectorPanel",
    "RigDescriptor",
    "discover_rigs",
    "BatchRetargetingTool",
    "RetargetError",
    "RetargetMapping",
    "RetargetResult",
    "DEFAULT_CONTROL_PREFIXES",
    "DEFAULT_JOINT_PREFIXES",
    "DEFAULT_REQUIRED_CONTROL_ATTRIBUTES",
    "DEFAULT_REQUIRED_HIERARCHY",
    "RigValidationIssue",
    "RigValidationReport",
    "validate_rig_import",
    "PlayblastAutomationTool",
    "PlayblastRequest",
    "PlayblastResult",
    "ReviewUploader",
    "build_playblast_filename",
    "AnimationDebuggerIssue",
    "AnimationDebuggerReport",
    "CacheLinkInfo",
    "ConstraintInfo",
    "FrameRangeInfo",
    "debug_animation",
    "DEFAULT_ALLOWED_PREFIXES",
    "DEFAULT_EXPECTED_ROOT",
    "DEFAULT_EXPECTED_SCALE",
    "DEFAULT_REQUIRED_JOINTS",
    "DEFAULT_SCALE_TOLERANCE",
    "UnrealExportIssue",
    "UnrealExportReport",
    "validate_unreal_export",
]
