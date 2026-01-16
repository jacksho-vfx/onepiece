"""Smoke tests for the Perona demo dashboard surface."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from apps.perona.web import dummy_dashboard


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(dummy_dashboard.app) as test_client:
        yield test_client


def test_demo_dashboard_ui_returns_html_shell(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "<title>Perona Dashboard</title>" in response.text


def test_demo_wrangler_scripts_can_be_listed_and_executed(
    client: TestClient,
) -> None:
    response = client.get("/wrangler/scripts")

    assert response.status_code == 200

    scripts = response.json()
    assert isinstance(scripts, list)
    assert scripts, "Expected demo Wrangler scripts to be available"

    script_id = scripts[0]["script_id"]
    run_response = client.post(f"/wrangler/scripts/{script_id}")

    assert run_response.status_code == 200

    result = run_response.json()
    assert result["script_id"] == script_id
    # assert result["status"] == "success"


def test_demo_shot_sequences_endpoint_returns_grouped_sequences(
    client: TestClient,
) -> None:
    response = client.get("/shots/sequences")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert data, "Expected demo sequences to be returned"

    for sequence in data:
        assert {"name", "shots"}.issubset(sequence)
        shot_names = {shot["sequence"] for shot in sequence["shots"]}
        assert shot_names == {sequence["name"]}
        assert sequence["shots"], "Expected grouped sequence to include shots"


def test_demo_dashboard_summary_returns_dummy_data(client: TestClient) -> None:
    response = client.get("/dashboard/summary")

    assert response.status_code == 200

    summary = response.json()
    assert summary["metrics"]["total_samples"] > 0
    assert summary["shots"]["total"] >= summary["shots"]["completed"]
    assert isinstance(summary["costs"]["currency"], str)
    assert summary["costs"]["currency"]


def test_demo_dashboard_summary_is_deterministic(client: TestClient) -> None:
    initial = client.get("/dashboard/summary")
    repeat = client.get("/dashboard/summary")

    assert initial.status_code == 200
    assert repeat.status_code == 200
    assert initial.json() == repeat.json()
