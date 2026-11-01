"""Unit tests for the ETL pipeline."""

from __future__ import annotations

import pytest

from app.core.errors import PayloadTooLargeError, UnprocessableError
from app.services.etl import process_csv

HEADER = b"timestamp,variable,value,unit\n"

BASE_CSV = HEADER + (
    b"2024-01-01T00:00:00Z,temperature,20.0,C\n"
    b"2024-01-01T00:01:00Z,temperature,20.5,C\n"
    b"2024-01-01T00:02:00Z,temperature,21.0,C\n"
    b"2024-01-01T00:02:00Z,temperature,21.2,C\n"  # duplicate timestamp: last wins
    b"2024-01-01T00:03:00Z,temperature,not-a-number,C\n"  # rejected value
    b"not-a-timestamp,temperature,22.0,C\n"  # rejected timestamp
    b"2024-01-01T00:04:00Z,temperature,20.8,C\n"
)


def test_process_csv_reports_quality_metrics() -> None:
    result = process_csv(BASE_CSV, filename="lab.csv")

    assert result.row_count == 4
    assert result.rejected_rows == 2
    assert result.stats["rows_read"] == 7
    assert result.stats["duplicates_removed"] == 1
    assert len(result.records) == 4
    assert all(record["variable"] == "temperature" for record in result.records)
    assert all(record["unit"] == "C" for record in result.records)
    assert result.checksum_sha256 == __import__("hashlib").sha256(BASE_CSV).hexdigest()


def test_process_csv_sorts_by_variable_and_timestamp() -> None:
    result = process_csv(BASE_CSV, filename="lab.csv")
    timestamps = [record["recorded_at"] for record in result.records]
    assert timestamps == sorted(timestamps)


def test_process_csv_flags_outliers_without_dropping_them() -> None:
    rows = [b"timestamp,value\n"]
    rows += [
        f"2024-02-01T00:{minute:02d}:00Z,{20.0 + (minute % 5) * 0.1}\n".encode()
        for minute in range(40)
    ]
    rows.append(b"2024-02-01T01:00:00Z,500.0\n")

    result = process_csv(b"".join(rows), filename="outliers.csv")

    assert result.row_count == 41
    assert result.outlier_rows == 1
    flagged = [record for record in result.records if record["is_outlier"]]
    assert len(flagged) == 1
    assert flagged[0]["value"] == pytest.approx(500.0)
    assert result.stats["variables"]["value"]["outliers"] == 1


def test_process_csv_supports_other_delimiters_and_custom_columns() -> None:
    payload = b"Date;Reading\n2024-03-01 10:00:00;1.5\n2024-03-01 10:01:00;1.7\n"

    result = process_csv(
        payload,
        filename="semicolon.csv",
        timestamp_column="Date",
        value_column="Reading",
        default_variable="pressure",
        default_unit="bar",
    )

    assert result.row_count == 2
    assert result.records[0]["variable"] == "pressure"
    assert result.records[0]["unit"] == "bar"
    assert result.records[0]["value"] == pytest.approx(1.5)


def test_process_csv_rejects_missing_columns() -> None:
    with pytest.raises(UnprocessableError) as excinfo:
        process_csv(b"timestamp,reading\n2024-01-01T00:00:00Z,1.0\n", filename="bad.csv")

    assert excinfo.value.details is not None
    assert "value" in excinfo.value.details["missing"]


def test_process_csv_rejects_files_without_valid_rows() -> None:
    payload = b"timestamp,value\nbad,also-bad\n"

    with pytest.raises(UnprocessableError, match="No valid rows"):
        process_csv(payload, filename="empty.csv")


def test_process_csv_rejects_empty_payload() -> None:
    with pytest.raises(UnprocessableError, match="empty"):
        process_csv(b"", filename="empty.csv")


def test_process_csv_enforces_size_limit() -> None:
    with pytest.raises(PayloadTooLargeError):
        process_csv(b"x" * (11 * 1024 * 1024), filename="huge.csv")


def test_process_csv_accepts_unix_seconds() -> None:
    result = process_csv(b"timestamp,value\n0,1.5\n3600,2.5\n", filename="epoch.csv")

    assert result.row_count == 2
    assert result.records[0]["recorded_at"].timestamp() == 0
    assert "Timestamps were interpreted as Unix seconds" in result.warnings


def test_process_csv_falls_back_to_cp1252() -> None:
    payload = b"timestamp,value,unit\n2024-01-01T00:00:00Z,1.0,\xb0C\n"

    result = process_csv(payload, filename="latin1.csv")

    assert result.records[0]["unit"] == "°C"
