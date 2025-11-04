"""OnePiece pipeline toolkit"""

import sys

import apps.onepiece.validate as validate  # re-export for convenience

__version__ = "1.0.0"

# Ensure legacy "onepiece" import paths resolve to the same package modules.
sys.modules.setdefault("onepiece", sys.modules[__name__])
sys.modules.setdefault("onepiece.validate", validate)

__all__ = ["__version__", "validate"]
