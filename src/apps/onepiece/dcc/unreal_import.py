"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_unreal_import = _import_module("libraries.onepiece.cli.dcc.unreal_import")

_sys.modules[__name__] = _unreal_import
