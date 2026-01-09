"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_templates = _import_module("libraries.onepiece.cli.shotgrid.templates")

_sys.modules[__name__] = _templates
