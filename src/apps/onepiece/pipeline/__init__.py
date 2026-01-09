"""Thin wrapper for OnePiece CLI commands."""

from libraries.onepiece.cli import pipeline as _pipeline
from libraries.onepiece.cli.pipeline import *  # noqa: F401,F403

_create_pipeline_client = _pipeline._create_pipeline_client
_serialised_definition_to_manifest = _pipeline._serialised_definition_to_manifest
