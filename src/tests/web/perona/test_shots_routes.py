from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from apps.perona.web.dashboard import app

from . import KNOWN_SEQUENCES

client = TestClient(app)


def test_shots_lifecycle_endpoint() -> None:
    response = client.get("/shots/lifecycle")
    assert response.status_code == 200
    data = response.json()
    assert data
    assert {"sequence", "shot_id", "current_stage"}.issubset(data[0].keys())


def test_shots_sequences_endpoint() -> None:
    response = client.get("/shots/sequences")
    assert response.status_code == 200
    data = response.json()
    assert data

    names = [item["name"] for item in data]
    assert len(names) == len(set(names))

    for sequence in data:
        shot_ids = [shot["shot_id"] for shot in sequence["shots"]]
        assert shot_ids == sorted(shot_ids)


def test_shots_summary_filters_by_sequence() -> None:
    response = client.get("/shots", params={"sequence": "SQ05"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["completed"] == 1
    assert data["active"] == 0
    assert data["by_sequence"] == [{"name": "SQ05", "shots": 1}]
    assert not data["active_shots"]


def test_shots_lifecycle_filters_by_artist() -> None:
    response = client.get("/shots/lifecycle", params={"artist": "M. Chen"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    shot = data[0]
    assert shot["sequence"] == "SQ12"
    assert shot["shot_id"] == "SQ12_SH010"


def test_shots_filters_by_date_range() -> None:
    params = {
        "start_date": "2024-05-17T12:00:00",
        "end_date": "2024-05-18T00:00:00",
    }
    response = client.get("/shots", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4
    sequences = {item["name"] for item in data["by_sequence"]}
    assert "SQ05" in sequences
    assert "SQ05" not in {shot["sequence"] for shot in data["active_shots"]}


def test_shots_filters_include_active_stages_within_window() -> None:
    now = datetime.utcnow()
    params = {
        "start_date": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
        "end_date": (now + timedelta(hours=1)).isoformat(timespec="seconds"),
    }
    response = client.get("/shots", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert {item["name"] for item in data["by_sequence"]} == {
        "SQ12",
        "SQ18",
        "SQ09",
    }
    active_sequences = {shot["sequence"] for shot in data["active_shots"]}
    assert {"SQ12", "SQ18", "SQ09"}.issubset(active_sequences)


def test_shot_sequences_support_filters() -> None:
    response = client.get("/shots/sequences", params={"artist": "R. Ali"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    sequence = data[0]
    assert sequence["name"] == "SQ18"
    assert {shot["shot_id"] for shot in sequence["shots"]} == {"SQ18_SH220"}


def test_shots_summary_endpoint() -> None:
    response = client.get("/shots")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 4
    sequences = {item["name"] for item in data["by_sequence"]}
    assert KNOWN_SEQUENCES.issubset(sequences)
    assert any(shot["current_stage"] for shot in data["active_shots"])
