"""Templates used by the Perona dashboard web UI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from apps.perona.version import PERONA_VERSION

_BASE_DIR = Path(__file__).resolve().parent
_DASHBOARD_TEMPLATE_PATH = _BASE_DIR / "templates" / "dashboard" / "index.html"


@lru_cache(maxsize=1)
def _load_dashboard_template() -> str:
    """Load the dashboard HTML template from disk."""

    return _DASHBOARD_TEMPLATE_PATH.read_text(encoding="utf-8")


def dashboard_index_html() -> str:
    """Return the bundled HTML shell for the interactive dashboard."""

    return _load_dashboard_template().replace("__PERONA_VERSION__", PERONA_VERSION)


__all__ = ["dashboard_index_html"]
