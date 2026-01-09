"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_info = _import_module("libraries.onepiece.cli.misc.info")

_sys.modules[__name__] = _info
