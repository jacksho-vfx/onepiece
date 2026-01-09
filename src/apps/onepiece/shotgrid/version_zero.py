"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_version_zero = _import_module("libraries.onepiece.cli.shotgrid.version_zero")

_sys.modules[__name__] = _version_zero
