"""Thin wrapper for OnePiece CLI commands."""

from libraries.creative.dcc.cinema4d.cleanup import cleanup_scene  # noqa: F401
from libraries.creative.dcc.cinema4d.gather import gather_references  # noqa: F401
from libraries.creative.dcc.cinema4d.validation import validate_package  # noqa: F401
from libraries.onepiece.cli.dcc.cinema4d import *  # noqa: F401,F403
