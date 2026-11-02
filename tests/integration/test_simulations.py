"""Integration tests for /api/v1/simulations."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

GBM_PAYLOAD: dict[str, Any] = {
    "name": "GBM baseline",
    "params": {"kind": "gbm", "s0": 100.0, "mu": 0.05, "sigma": 0.2},
    "n_paths": 500,
    "n_steps": 60,
    "seed": 1234,
    "threshold": 110.0,
}


def create_simulation(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/api/v1/simulations", json={**GBM_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_simulation_persists_results(client: TestClient) -> None:
    body = create_simulation(client)

    assert body["status"] == "completed"
    assert body["model"] == "gbm"
    assert body["n_paths"] == 500
    assert body["duration_ms"] is not None
    assert body["finished_at"] is not None

    summary = body["summary"]
    assert summary["minimum"] <= summary["p05"] < summary["p50"]
    assert summary["p50"] < summary["p95"] <= summary["maximum"]
    assert 0.0 <= summary["prob_above_threshold"] <= 1.0
    assert len(summary["histogram"]["counts"]) == 24

    fetched = client.get(f"/api/v1/simulations/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_same_seed_is_reproducible_through_the_api(client: TestClient) -> None:
    first = create_simulation(client)
    second = create_simulation(client, name="Same seed again")

    first_values = client.get(f"/api/v1/simulations/{first['id']}/results?sample=500").json()
    second_values = client.get(f"/api/v1/simulations/{second['id']}/results?sample=500").json()

    assert first_values["terminal_values"] == second_values["terminal_values"]


def test_results_endpoint_returns_a_sample(client: TestClient) -> None:
    run = create_simulation(client)

    response = client.get(f"/api/v1/simulations/{run['id']}/results?sample=25")

    assert response.status_code == 200
    body = response.json()
    assert body["returned"] == 25
    assert body["total_paths"] == 500
    assert len(body["terminal_values"]) == 25


def test_paths_endpoint_paginates(client: TestClient) -> None:
    run = create_simulation(client)

    response = client.get(f"/api/v1/simulations/{run['id']}/paths?limit=10&offset=5")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 500
    assert [item["path_index"] for item in body["items"]] == list(range(5, 15))


def test_histogram_endpoint(client: TestClient) -> None:
    run = create_simulation(client)

    response = client.get(f"/api/v1/simulations/{run['id']}/histogram")

    assert response.status_code == 200
    body = response.json()
    assert len(body["counts"]) == 24
    assert len(body["bins"]) == 25
    assert sum(body["counts"]) == 500


def test_trajectories_endpoint(client: TestClient) -> None:
    run = create_simulation(client)

    response = client.get(f"/api/v1/simulations/{run['id']}/trajectories")

    assert response.status_code == 200
    body = response.json()
    assert body["total_paths"] == 500
    assert body["sampled_paths"] == 25
    assert len(body["paths"]) == 25
    assert len(body["steps"]) == 61  # n_steps=60 -> 61 points
    assert all(len(path) == 61 for path in body["paths"])
    assert body["dt"] == pytest.approx(1 / 252)


def test_list_filters_by_status(client: TestClient) -> None:
    create_simulation(client)
    create_simulation(client, name="Second run")

    response = client.get("/api/v1/simulations?status=completed")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    empty = client.get("/api/v1/simulations?status=failed").json()
    assert empty["total"] == 0


def test_delete_removes_the_run(client: TestClient) -> None:
    run = create_simulation(client)

    deletion = client.delete(f"/api/v1/simulations/{run['id']}")
    assert deletion.status_code == 204

    assert client.get(f"/api/v1/simulations/{run['id']}").status_code == 404
    assert client.get(f"/api/v1/simulations/{run['id']}/paths").status_code == 404


def test_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/simulations/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_paths": 10},
        {"n_paths": 20_000, "n_steps": 5_000},
        {"params": {"kind": "gbm", "s0": -1.0, "mu": 0.0, "sigma": 0.2}},
        {"params": {"kind": "nope"}},
        {"seed": -5},
    ],
)
def test_invalid_payloads_return_422(client: TestClient, overrides: dict[str, Any]) -> None:
    response = client.post("/api/v1/simulations", json={**GBM_PAYLOAD, **overrides})
    assert response.status_code == 422


def test_overview_aggregates_runs(client: TestClient) -> None:
    create_simulation(client)
    create_simulation(client, name="Second run")

    body = client.get("/api/v1/overview").json()

    assert body["simulations_total"] == 2
    assert body["simulations_completed"] == 2
    assert body["paths_simulated"] == 1_000
    assert body["avg_duration_ms"] is not None


def test_failed_execution_is_recorded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("numerical explosion")

    monkeypatch.setattr("app.services.simulations.montecarlo.simulate", explode)

    response = client.post("/api/v1/simulations", json=GBM_PAYLOAD)

    assert response.status_code == 500
    assert response.json()["detail"] == "The simulation failed while executing the model"

    runs = client.get("/api/v1/simulations").json()["items"]
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert "numerical explosion" in runs[0]["error"]

    failed_id = runs[0]["id"]
    assert client.get(f"/api/v1/simulations/{failed_id}/results").status_code == 409
    assert client.get(f"/api/v1/simulations/{failed_id}/paths").status_code == 409
    assert client.get(f"/api/v1/simulations/{failed_id}/histogram").status_code == 409
    assert client.get(f"/api/v1/simulations/{failed_id}/trajectories").status_code == 409
