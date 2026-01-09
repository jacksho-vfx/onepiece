"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_deliver = _import_module("libraries.onepiece.cli.shotgrid.deliver")

_sys.modules[__name__] = _deliver
