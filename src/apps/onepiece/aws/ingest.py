"""Thin wrapper for OnePiece CLI commands."""

from libraries.automation.ingest import MediaIngestService  # noqa: F401
from libraries.integrations.shotgrid.client import ShotgridClient  # noqa: F401
from libraries.onepiece.cli.aws import ingest as _ingest
from libraries.onepiece.cli.aws.ingest import *  # noqa: F401,F403

_prepare_ingest_options = _ingest._prepare_ingest_options
