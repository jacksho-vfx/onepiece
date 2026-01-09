"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_dcc_environment = _import_module("libraries.onepiece.cli.validate.dcc_environment")

_sys.modules[__name__] = _dcc_environment
