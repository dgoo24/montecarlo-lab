"""Integration tests for the health and meta endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"


def test_readiness_checks_the_database(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "up"}


def test_root_exposes_links(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_openapi_schema_is_generated(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/simulations" in schema["paths"]
    assert "/api/v1/datasets" in schema["paths"]
    assert "/api/v1/overview" in schema["paths"]
