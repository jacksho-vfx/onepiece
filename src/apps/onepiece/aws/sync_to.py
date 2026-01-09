"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys
from importlib import import_module as _import_module

_sync_to = _import_module("libraries.onepiece.cli.aws.sync_to")

_sys.modules[__name__] = _sync_to
