from __future__ import annotations

from fastapi.testclient import TestClient

from apps.perona.web import wrangler as wrangler_module


def test_wrangler_scripts_listing_returns_metadata(client: TestClient) -> None:
    wrangler_module.register_script(
        wrangler_module.WranglerScriptMetadata(
            script_id="cache.refresh",
            name="Refresh cache",
            description="Rebuild cached analytics",
        ),
        lambda: {"status": "success", "message": "ok"},
    )

    response = client.get("/wrangler/scripts")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    scripts = {item["script_id"]: item for item in payload}
    assert scripts["analyse_cost_drivers"]["name"] == "Analyse cost drivers"
    assert "cost inputs" in scripts["analyse_cost_drivers"]["description"].lower()
    assert scripts["analyse_cost_drivers"]["tags"] == [
        "cost",
        "insights",
        "telemetry",
    ]
    assert "boost_gpu_utilisation" in scripts
    assert scripts["boost_gpu_utilisation"]["name"] == "Boost GPU utilisation"
    assert scripts["boost_gpu_utilisation"]["description"]
    assert scripts["boost_gpu_utilisation"]["tags"] == ["rendering", "utilisation"]

    assert scripts["audit_telemetry_coverage"]["name"] == "Audit telemetry coverage"
    assert "telemetry" in scripts["audit_telemetry_coverage"]["description"].lower()
    assert scripts["audit_telemetry_coverage"]["tags"] == [
        "telemetry",
        "coverage",
        "health",
    ]

    assert scripts["check_telemetry_freshness"]["name"] == "Check telemetry freshness"
    assert "telemetry" in scripts["check_telemetry_freshness"]["description"].lower()
    assert scripts["check_telemetry_freshness"]["tags"] == ["telemetry", "health"]

    assert scripts["spin_down_idle_workers"]["name"] == "Spin down idle GPU workers"
    assert "GPU nodes" in scripts["spin_down_idle_workers"]["description"]
    assert scripts["spin_down_idle_workers"]["tags"] == [
        "rendering",
        "capacity",
        "cost",
    ]

    assert scripts["list_failing_jobs"]["name"] == "List failing jobs"
    assert "critical shots" in scripts["list_failing_jobs"]["description"]
    assert scripts["list_failing_jobs"]["tags"] == ["risk", "shots"]

    assert (
        scripts["flag_frame_time_regressions"]["name"] == "Flag frame time regressions"
    )
    assert "frame time" in scripts["flag_frame_time_regressions"]["description"].lower()
    assert scripts["flag_frame_time_regressions"]["tags"] == [
        "rendering",
        "performance",
    ]

    assert (
        scripts["flag_render_volatility"]["name"] == "Flag render volatility hotspots"
    )
    assert "volatile" in scripts["flag_render_volatility"]["description"].lower()
    assert scripts["flag_render_volatility"]["tags"] == [
        "rendering",
        "utilisation",
    ]

    assert scripts["rebuild_unstable_caches"]["name"] == "Rebuild unstable caches"
    assert (
        "cache stability" in scripts["rebuild_unstable_caches"]["description"].lower()
    )
    assert scripts["rebuild_unstable_caches"]["tags"] == [
        "risk",
        "caches",
        "simulation",
    ]

    assert scripts["flag_render_error_streaks"]["name"] == "Flag render error streaks"
    assert "consecutive" in scripts["flag_render_error_streaks"]["description"].lower()
    assert scripts["flag_render_error_streaks"]["tags"] == [
        "rendering",
        "errors",
        "shots",
    ]

    assert scripts["explain_pnl_delta"]["name"] == "Explain P&L delta"
    assert "render spend" in scripts["explain_pnl_delta"]["description"].lower()
    assert scripts["explain_pnl_delta"]["tags"] == [
        "finance",
        "pnl",
        "insights",
    ]

    assert (
        scripts["evaluate_optimisation_playbook"]["name"]
        == "Evaluate optimisation playbook"
    )
    assert (
        "optimisation"
        in scripts["evaluate_optimisation_playbook"]["description"].lower()
    )
    assert scripts["evaluate_optimisation_playbook"]["tags"] == [
        "cost",
        "optimisation",
        "playbook",
    ]

    assert (
        scripts["escalate_deadline_shots"]["name"]
        == "Escalate deadline-sensitive shots"
    )
    assert "deadline" in scripts["escalate_deadline_shots"]["description"].lower()
    assert scripts["escalate_deadline_shots"]["tags"] == [
        "risk",
        "shots",
        "deadline",
    ]

    assert (
        scripts["highlight_stage_bottlenecks"]["name"] == "Highlight stage bottlenecks"
    )
    assert (
        "busiest stage" in scripts["highlight_stage_bottlenecks"]["description"].lower()
    )
    assert scripts["highlight_stage_bottlenecks"]["tags"] == [
        "production",
        "shots",
    ]

    assert scripts["cache.refresh"] == {
        "script_id": "cache.refresh",
        "name": "Refresh cache",
        "description": "Rebuild cached analytics",
        "tags": [],
    }


def test_wrangler_execute_missing_script_returns_404(client: TestClient) -> None:
    response = client.post("/wrangler/scripts/unknown-task")

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown Wrangler script."}


def test_wrangler_execute_script_returns_payload(client: TestClient) -> None:
    async def runner() -> wrangler_module.WranglerScriptResult:
        return wrangler_module.WranglerScriptResult(
            script_id="reindex",
            status="success",
            message="Completed",
            payload={"refreshed": 12},
        )

    wrangler_module.register_script(
        wrangler_module.WranglerScriptMetadata(
            script_id="reindex",
            name="Reindex sequences",
            description="Refreshes downstream search indices",
        ),
        runner,
    )

    response = client.post("/wrangler/scripts/reindex")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "reindex"
    assert payload["status"] == "success"
    assert payload["message"] == "Completed"
    assert payload["payload"] == {"refreshed": 12}
