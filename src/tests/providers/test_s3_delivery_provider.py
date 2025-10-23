from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from apps.trafalgar.providers.providers import S3DeliveryProvider


class RecordingPaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages
        self.calls: list[dict[str, Any]] = []

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return self._pages


class DummyClient:
    def __init__(self, paginator: RecordingPaginator) -> None:
        self.paginator = paginator
        self.operations: list[str] = []

    def get_paginator(self, operation_name: str) -> RecordingPaginator:
        self.operations.append(operation_name)
        return self.paginator


def test_s3_delivery_provider_lists_manifests() -> None:
    first_time = datetime(2023, 5, 20, 8, 30, tzinfo=timezone.utc)
    second_time = datetime(2023, 5, 21, 9, 15, tzinfo=timezone.utc)
    paginator = RecordingPaginator(
        [
            {
                "Contents": [
                    {
                        "Key": "atlas/deliveries/daily-0520/manifest.json",
                        "LastModified": first_time,
                        "Size": 4096,
                        "ETag": '"abc123"',
                    },
                    {
                        "Key": "atlas/deliveries/daily-0521/manifest.json",
                        "LastModified": second_time,
                        "Size": 8192,
                        "ETag": '"def456"',
                    },
                    {
                        "Key": "atlas/deliveries/daily-0521/manifest.csv",
                        "LastModified": second_time,
                        "Size": 1024,
                    },
                ]
            }
        ]
    )
    client = DummyClient(paginator)
    provider = S3DeliveryProvider(
        client=client,
        bucket="deliveries-bucket",
        prefix_template="{project}/deliveries/",
    )

    deliveries = provider.list_deliveries("atlas")

    assert client.operations == ["list_objects_v2"]
    assert paginator.calls == [
        {"Bucket": "deliveries-bucket", "Prefix": "atlas/deliveries/"}
    ]
    assert [delivery["key"] for delivery in deliveries] == [
        "atlas/deliveries/daily-0521/manifest.json",
        "atlas/deliveries/daily-0520/manifest.json",
    ]

    latest = deliveries[0]
    assert latest["project"] == "atlas"
    assert latest["bucket"] == "deliveries-bucket"
    assert latest["manifest"] == "atlas/deliveries/daily-0521/manifest.json"
    assert latest["delivery_id"] == "daily-0521"
    assert latest["name"] == "daily-0521"
    assert latest["created_at"] == "2023-05-21T09:15:00+00:00"
    assert latest["size"] == 8192
    assert latest["etag"] == "def456"


def test_s3_delivery_provider_requires_bucket() -> None:
    provider = S3DeliveryProvider(client=object(), bucket=None)

    deliveries = provider.list_deliveries("any-project")

    assert deliveries == []


def test_s3_delivery_provider_handles_service_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingPaginator:
        def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("boom")

    class ClientWithFailingPaginator:
        def get_paginator(self, operation_name: str) -> FailingPaginator:
            return FailingPaginator()

    provider = S3DeliveryProvider(
        client=ClientWithFailingPaginator(),
        bucket="deliveries-bucket",
        prefix_template="{project}/deliveries/",
    )

    with caplog.at_level("ERROR"):
        deliveries = provider.list_deliveries("atlas")

    assert deliveries == []
    assert any("s3_delivery_list_failed" in record.message for record in caplog.records)
