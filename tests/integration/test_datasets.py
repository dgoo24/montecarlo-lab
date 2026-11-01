"""Integration tests for dataset ingestion and exploration."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def build_csv() -> bytes:
    rows = ["timestamp,variable,value,unit"]
    for minute in range(30):
        rows.append(f"2024-05-01T00:{minute:02d}:00Z,temperature,{20.0 + (minute % 3) * 0.1:.1f},C")
    rows.append("2024-05-01T00:40:00Z,temperature,60.0,C")  # outlier
    rows.append("2024-05-01T00:00:00Z,temperature,20.1,C")  # duplicate timestamp
    rows.append("2024-05-01T00:41:00Z,temperature,not-a-number,C")  # rejected
    for minute in range(5):
        rows.append(f"2024-05-01T00:{minute:02d}:30Z,pressure,{1.0 + minute * 0.01:.2f},bar")
    return ("\n".join(rows) + "\n").encode()


def upload(client: TestClient, payload: bytes | None = None) -> dict:
    response = client.post(
        "/api/v1/datasets",
        files={"file": ("measurements.csv", payload or build_csv(), "text/csv")},
        data={"name": "May lab run"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_reports_etl_metrics(client: TestClient) -> None:
    body = upload(client)

    assert body["status"] == "ready"
    assert body["row_count"] == 36
    assert body["rejected_rows"] == 1
    assert body["outlier_rows"] == 1
    assert len(body["checksum_sha256"]) == 64

    stats = body["stats"]
    assert stats["rows_read"] == 38
    assert stats["duplicates_removed"] == 1
    assert stats["variables"]["temperature"]["count"] == 31
    assert stats["variables"]["pressure"]["count"] == 5
    assert stats["time_range"]["start"].startswith("2024-05-01T00:00:00")


def test_stats_are_recomputed_from_the_database(client: TestClient) -> None:
    dataset = upload(client)

    response = client.get(f"/api/v1/datasets/{dataset['id']}/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 36
    variables = {item["variable"]: item for item in body["variables"]}
    assert variables["pressure"]["count"] == 5
    assert variables["pressure"]["mean"] == pytest.approx(1.02)
    assert variables["temperature"]["outliers"] == 1
    assert body["stored_stats"]["rows_read"] == 38


def test_measurements_can_be_filtered(client: TestClient) -> None:
    dataset = upload(client)

    pressure = client.get(f"/api/v1/datasets/{dataset['id']}/measurements?variable=pressure").json()
    assert pressure["total"] == 5
    assert {item["unit"] for item in pressure["items"]} == {"bar"}

    outliers = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements?only_outliers=true"
    ).json()
    assert outliers["total"] == 1
    assert outliers["items"][0]["value"] == 60.0
    assert outliers["items"][0]["is_outlier"] is True


def test_list_datasets(client: TestClient) -> None:
    upload(client)
    upload(client)

    body = client.get("/api/v1/datasets").json()

    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_delete_dataset_cascades(client: TestClient) -> None:
    dataset = upload(client)

    assert client.delete(f"/api/v1/datasets/{dataset['id']}").status_code == 204
    assert client.get(f"/api/v1/datasets/{dataset['id']}").status_code == 404
    assert client.get(f"/api/v1/datasets/{dataset['id']}/measurements").status_code == 404


def test_upload_without_value_column_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/datasets",
        files={"file": ("bad.csv", b"timestamp,reading\n2024-01-01T00:00:00Z,1.0\n", "text/csv")},
        data={"name": "bad"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The CSV is missing required columns"
    assert "value" in response.json()["context"]["missing"]


def test_upload_with_no_valid_rows_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/datasets",
        files={"file": ("bad.csv", b"timestamp,value\nnope,nope\n", "text/csv")},
        data={"name": "bad"},
    )

    assert response.status_code == 422


def test_overview_counts_datasets(client: TestClient) -> None:
    upload(client)

    body = client.get("/api/v1/overview").json()

    assert body["datasets_total"] == 1
    assert body["measurements_total"] == 36
