"""Thin wrapper for OnePiece CLI commands."""

from libraries.platform.validations.dcc import (  # noqa: F401
    check_dcc_environment,
    validate_dcc,
)
from libraries.onepiece.cli.validate.dcc_environment import *  # noqa: F401,F403
