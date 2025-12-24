"""Bootstrap the OnePiece menu and panel when Maya starts."""

from __future__ import annotations

import sys
from pathlib import Path
import traceback

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))

try:  # pragma: no cover - executed inside Maya
    from .onepiece_menu import bootstrap
except Exception:  # pragma: no cover - executed inside Maya
    traceback.print_exc()
else:  # pragma: no cover - executed inside Maya
    bootstrap()
