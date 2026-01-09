"""Thin wrapper for OnePiece CLI commands."""

import sys as _sys

from libraries.onepiece.cli import pipeline as _pipeline
from libraries.onepiece.cli.pipeline import clients as _clients
from libraries.onepiece.cli.pipeline import io as _io
from libraries.onepiece.cli.pipeline import output as _output
from libraries.onepiece.cli.pipeline import schema as _schema

_sys.modules[__name__] = _pipeline
_sys.modules[f"{__name__}.clients"] = _clients
_sys.modules[f"{__name__}.io"] = _io
_sys.modules[f"{__name__}.output"] = _output
_sys.modules[f"{__name__}.schema"] = _schema
