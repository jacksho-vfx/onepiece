"""Helpers for mirroring folders with :command:`aws s3 sync`."""

from pathlib import Path
from typing import Literal

import logging
import subprocess

log = logging.getLogger(__name__)

ShowType = Literal["vfx", "prod"]
ContextFolder = Literal["vendor_out", "vendor_in", "client_out", "client_in"]


def _resolve_context(show_type: ShowType, direction: Literal["to", "from"]) -> ContextFolder:
    """
    Determine the context folder from show type and direction.

    Args:
        show_type: 'vfx' or 'prod'
        direction: 'to' (upload) or 'from' (download)
    """
    if show_type == "vfx":
        return "vendor_out" if direction == "to" else "vendor_in"
    return "client_out" if direction == "to" else "client_in"


def _build_s3_uri(bucket: str, show_code: str, folder: str, context: ContextFolder) -> str:
    """Return the canonical S3 URI for this show folder."""
    return f"s3://{bucket}/{context}/{show_code}/{folder}/"


def sync_to_bucket(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: str | Path,
    show_type: ShowType = "vfx",
    delete: bool = False,
    profile: str | None = None,
) -> None:
    """
    Sync a local folder TO an S3 bucket using `aws s3 sync`.

    Args:
        bucket: Target S3 bucket name.
        show_code: Show identifier (e.g. 'SHOW123').
        folder: Folder name under the show (e.g. 'plates').
        local_path: Local directory to upload.
        show_type: 'vfx' or 'prod' (default: vfx).
        delete: If True, delete remote files not present locally.
        profile: Optional named AWS CLI profile.
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Local path does not exist: {local_path}")

    context = _resolve_context(show_type, "to")
    s3_uri = _build_s3_uri(bucket, show_code, folder, context)
    log.info(
        "aws_s3_sync_to local=%s s3=%s delete=%s",
        str(local_path),
        s3_uri,
        delete,
    )

    cmd = ["aws"]
    if profile:
        cmd.extend(["--profile", profile])
    cmd += ["s3", "sync", str(local_path), s3_uri]
    if delete:
        cmd.append("--delete")

    subprocess.run(cmd, check=True)


def sync_from_bucket(
    bucket: str,
    show_code: str,
    folder: str,
    local_path: str | Path,
    show_type: ShowType = "vfx",
    delete: bool = False,
    profile: str | None = None,
) -> None:
    """
    Sync an S3 bucket folder TO a local folder using `aws s3 sync`.

    Args:
        bucket: Source S3 bucket name.
        show_code: Show identifier.
        folder: Folder name under the show.
        local_path: Local directory to download into.
        show_type: 'vfx' or 'prod' (default: vfx).
        delete: If True, delete local files not present in S3.
        profile: Optional named AWS CLI profile.
    """
    local_path = Path(local_path)
    local_path.mkdir(parents=True, exist_ok=True)
    
    context = _resolve_context(show_type, "from")
    s3_uri = _build_s3_uri(bucket, show_code, folder, context)
    log.info(
        "aws_s3_sync_from s3=%s local=%s delete=%s",
        s3_uri,
        str(local_path),
        delete,
    )

    cmd = ["aws"]
    if profile:
        cmd.extend(["--profile", profile])
    cmd += ["s3", "sync", s3_uri, str(local_path)]
    if delete:
        cmd.append("--delete")

    subprocess.run(cmd, check=True)

