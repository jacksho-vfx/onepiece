"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_package_playlist = _import_module("libraries.onepiece.cli.shotgrid.package_playlist")

_sys.modules[__name__] = _package_playlist
