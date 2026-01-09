"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_cinema4d = _import_module("libraries.onepiece.cli.dcc.cinema4d")

_sys.modules[__name__] = _cinema4d
