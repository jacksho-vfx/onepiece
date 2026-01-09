"""Thin wrapper for OnePiece CLI commands."""

from libraries.automation.render.deadline import submit_job  # noqa: F401
from libraries.automation.render.geometry import optimize_geometry  # noqa: F401
from libraries.onepiece.cli.render.submit.optimize_deadline_command import *  # noqa: F401,F403
