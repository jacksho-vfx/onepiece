"""Smoke tests for the Perona demo dashboard surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.perona.web import dummy_dashboard


client = TestClient(dummy_dashboard.app)


def test_demo_dashboard_ui_returns_html_shell() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "<title>Perona Dashboard</title>" in response.text


def test_demo_shot_sequences_endpoint_returns_grouped_sequences() -> None:
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


def test_demo_dashboard_summary_returns_dummy_data() -> None:
    response = client.get("/dashboard/summary")

    assert response.status_code == 200

    summary = response.json()
    assert summary["metrics"]["total_samples"] > 0
    assert summary["shots"]["total"] >= summary["shots"]["completed"]
    assert isinstance(summary["costs"]["currency"], str)
    assert summary["costs"]["currency"]
