"""Helpers to enumerate S3 objects for reconciliation."""

import os
from typing import Dict, List, Optional, Any

import structlog

from libraries.reconcile.parsing import extract_entity, extract_version

log = structlog.get_logger(__name__)

S3_BUCKET_ENV = "ONEPIECE_S3_BUCKET"


def _ensure_boto3() -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - exercised in failure scenarios
        raise RuntimeError("boto3 is required to scan S3") from exc
    return boto3


def scan_s3_context(
    project_name: str,
    context: str,
    *,
    bucket: Optional[str] = None,
    scope: str = "shots",
    s3_client: Optional[object] = None,
) -> List[Dict[str, str]]:
    """Return objects stored under ``context/<project_name>`` in S3."""

    bucket_name = bucket or os.environ.get(S3_BUCKET_ENV)
    if not bucket_name:
        raise RuntimeError("S3 bucket not configured. Set ONEPIECE_S3_BUCKET.")

    boto3 = _ensure_boto3()
    client: Any = s3_client or boto3.client("s3")
    prefix = f"{context}/{project_name}/"

    paginator = client.get_paginator("list_objects_v2")
    results: List[Dict[str, str]] = []
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if not key:
                continue
            parts = key.split("/")
            entity = extract_entity(parts, scope=scope)
            version = extract_version(parts)
            if not entity or not version:
                continue
            results.append({"shot": entity, "version": version, "key": key})

    log.info(
        "s3.scan.complete",
        bucket=bucket_name,
        context=context,
        project=project_name,
        files=len(results),
    )
    return results
