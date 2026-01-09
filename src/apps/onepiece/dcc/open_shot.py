"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_open_shot = _import_module("libraries.onepiece.cli.dcc.open_shot")

_sys.modules[__name__] = _open_shot
