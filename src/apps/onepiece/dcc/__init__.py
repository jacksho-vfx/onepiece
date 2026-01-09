"""Thin wrapper for OnePiece CLI commands."""

from importlib import import_module as _import_module

from libraries.onepiece.cli.dcc import *  # noqa: F401,F403

cinema4d = _import_module("apps.onepiece.dcc.cinema4d")
