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
    sys.modules.setdefault("pymel.core", types.ModuleType("pymel.core"))
    sys.modules.setdefault("pymel.core.system", types.ModuleType("pymel.core.system"))
    sys.modules.setdefault("pymel.core.general", types.ModuleType("pymel.core.general"))

# --------------------------------------------------------------------------- #
# Import public submodules (these can now import safely)
# --------------------------------------------------------------------------- #
from .batch_retargeting import (  # noqa: F401
    BatchRetargetingTool,
    RetargetError,
    RetargetMapping,
    RetargetResult,
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
    "BatchRetargetingTool",
    "RetargetError",
    "RetargetMapping",
    "RetargetResult",
    "DEFAULT_ALLOWED_PREFIXES",
    "DEFAULT_EXPECTED_ROOT",
    "DEFAULT_EXPECTED_SCALE",
    "DEFAULT_REQUIRED_JOINTS",
    "DEFAULT_SCALE_TOLERANCE",
    "UnrealExportIssue",
    "UnrealExportReport",
    "validate_unreal_export",
]
