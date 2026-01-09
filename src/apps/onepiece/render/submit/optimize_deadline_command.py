"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_optimize_deadline_command = _import_module(
    "libraries.onepiece.cli.render.submit.optimize_deadline_command"
)

_sys.modules[__name__] = _optimize_deadline_command
