"""Thin wrapper for OnePiece CLI commands."""

from libraries.onepiece.cli.render import submit as _submit
from libraries.onepiece.cli.render.submit import *  # noqa: F401,F403

_refresh_capabilities_cache = _submit._refresh_capabilities_cache
