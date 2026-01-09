"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_upload_version = _import_module("libraries.onepiece.cli.shotgrid.upload_version")

_sys.modules[__name__] = _upload_version
