import sys
from types import SimpleNamespace

from libraries.integrations.aws import scanner


class _FailingBoto3:
    def client(self, *_args, **_kwargs):  # pragma: no cover - defensive only
        raise AssertionError("boto3 client should not be called when a client is injected")


class FakePaginator:
    def __init__(self, expected_bucket, expected_prefix, pages):
        self.expected_bucket = expected_bucket
        self.expected_prefix = expected_prefix
        self.pages = pages
        self.calls = []

    def paginate(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["Bucket"] == self.expected_bucket
        assert kwargs["Prefix"] == self.expected_prefix
        for page in self.pages:
            yield page


class FakeClient:
    def __init__(self, paginator):
        self.paginator = paginator
        self.requested_operation = None

    def get_paginator(self, name):
        self.requested_operation = name
        assert name == "list_objects_v2"
        return self.paginator


def _build_page(*keys):
    contents = [{"Key": key} for key in keys]
    return {"Contents": contents}


def test_scan_s3_context_uses_injected_client_without_boto3(monkeypatch):
    failing_module = _FailingBoto3()
    monkeypatch.setitem(sys.modules, "boto3", failing_module)

    bucket = "injected-bucket"
    project = "demo_project"
    context = "context"
    expected_prefix = f"{context}/{project}/"
    paginator = FakePaginator(
        bucket,
        expected_prefix,
        [
            _build_page("context/demo_project/ep001_sc01_0001/v001/file.mov"),
            _build_page("context/demo_project/ep001_sc01_0001/v002/alt.mov"),
        ],
    )
    client = FakeClient(paginator)

    results = scanner.scan_s3_context(
        project,
        context,
        bucket=bucket,
        s3_client=client,
    )

    assert results == [
        {
            "shot": "ep001_sc01_0001",
            "version": "v001",
            "key": "context/demo_project/ep001_sc01_0001/v001/file.mov",
        },
        {
            "shot": "ep001_sc01_0001",
            "version": "v002",
            "key": "context/demo_project/ep001_sc01_0001/v002/alt.mov",
        },
    ]
    assert client.requested_operation == "list_objects_v2"
    assert paginator.calls == [
        {"Bucket": bucket, "Prefix": expected_prefix}
    ]


def test_scan_s3_context_uses_boto3_when_client_missing(monkeypatch):
    bucket = "env-bucket"
    project = "demo_project"
    context = "context"
    expected_prefix = f"{context}/{project}/"

    paginator = FakePaginator(
        bucket,
        expected_prefix,
        [
            _build_page("context/demo_project/ep001_sc01_0001/v001/file.mov"),
            _build_page("context/demo_project/ep001_sc01_0002/v010/file.mov"),
        ],
    )
    fake_client = FakeClient(paginator)

    service_calls = []

    def fake_client_factory(service):
        service_calls.append(service)
        assert service == "s3"
        return fake_client

    fake_boto3 = SimpleNamespace(client=fake_client_factory)
    calls = {"ensure": 0}

    def fake_ensure_boto3():
        calls["ensure"] += 1
        return fake_boto3

    monkeypatch.setenv(scanner.S3_BUCKET_ENV, bucket)
    monkeypatch.setattr(scanner, "_ensure_boto3", fake_ensure_boto3)

    results = scanner.scan_s3_context(project, context)

    assert calls["ensure"] == 1
    assert service_calls == ["s3"]
    assert fake_client.requested_operation == "list_objects_v2"
    assert paginator.calls == [
        {"Bucket": bucket, "Prefix": expected_prefix}
    ]
    assert results == [
        {
            "shot": "ep001_sc01_0001",
            "version": "v001",
            "key": "context/demo_project/ep001_sc01_0001/v001/file.mov",
        },
        {
            "shot": "ep001_sc01_0002",
            "version": "v010",
            "key": "context/demo_project/ep001_sc01_0002/v010/file.mov",
        },
    ]

    monkeypatch.delenv(scanner.S3_BUCKET_ENV, raising=False)
