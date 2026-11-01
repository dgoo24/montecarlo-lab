"""ETL for experimental data: parse, validate, de-duplicate, flag and persist.

The pipeline is intentionally conservative:

* invalid rows (unparseable timestamp or non-numeric value) are **rejected**
  and counted, never silently coerced;
* duplicated ``(variable, timestamp)`` pairs keep the last observation;
* outliers are **flagged** (IQR rule) but preserved, because deleting extreme
  measurements destroys the evidence a scientist may need later.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import case, delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError, PayloadTooLargeError, UnprocessableError
from app.db.models import Dataset, Measurement

CHUNK_SIZE = 5_000
IQR_FACTOR = 1.5
_MAX_ERROR_CHARS = 500


@dataclass(slots=True)
class ETLResult:
    """Outcome of parsing one CSV file."""

    records: list[dict[str, Any]]
    stats: dict[str, Any]
    row_count: int
    rejected_rows: int
    outlier_rows: int
    checksum_sha256: str
    warnings: list[str] = field(default_factory=list)


def _normalise_column(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def _detect_separator(sample: str) -> str:
    counts = {sep: sample.count(sep) for sep in (",", ";", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _read_csv(content: bytes) -> pd.DataFrame:
    sample = content[:8_192].decode("utf-8", errors="replace")
    separator = _detect_separator(sample)

    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return pd.read_csv(
                io.BytesIO(content),
                sep=separator,
                encoding=encoding,
                engine="python",
            )
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError as exc:
            raise UnprocessableError("The uploaded file is empty") from exc
        except pd.errors.ParserError as exc:
            raise UnprocessableError(
                "The file could not be parsed as delimited text",
                {"error": str(exc)[:_MAX_ERROR_CHARS]},
            ) from exc

    raise UnprocessableError("The file could not be decoded as UTF-8 or CP1252")


def process_csv(
    content: bytes,
    *,
    filename: str,
    timestamp_column: str = "timestamp",
    value_column: str = "value",
    default_variable: str = "value",
    default_unit: str | None = None,
) -> ETLResult:
    """Parse and validate a CSV payload, returning ready-to-insert records."""
    settings = get_settings()
    if not content:
        raise UnprocessableError("The uploaded file is empty")
    if len(content) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            "The uploaded file exceeds the maximum allowed size",
            {"max_bytes": settings.max_upload_bytes, "received_bytes": len(content)},
        )

    checksum = hashlib.sha256(content).hexdigest()
    frame = _read_csv(content)

    if frame.empty:
        raise UnprocessableError("The CSV file contains a header but no data rows")
    if len(frame) > settings.max_dataset_rows:
        raise PayloadTooLargeError(
            "The dataset has too many rows",
            {"max_rows": settings.max_dataset_rows, "received_rows": len(frame)},
        )

    frame.columns = [_normalise_column(column) for column in frame.columns]
    timestamp_column = _normalise_column(timestamp_column)
    value_column = _normalise_column(value_column)

    if timestamp_column == value_column:
        raise UnprocessableError("timestamp_column and value_column must be different")
    missing = [c for c in (timestamp_column, value_column) if c not in frame.columns]
    if missing:
        raise UnprocessableError(
            "The CSV is missing required columns",
            {"missing": missing, "found": list(frame.columns)},
        )

    raw_rows = len(frame)
    warnings: list[str] = []

    if pd.api.types.is_numeric_dtype(frame[timestamp_column]):
        recorded_at = pd.to_datetime(frame[timestamp_column], unit="s", utc=True, errors="coerce")
        warnings.append("Timestamps were interpreted as Unix seconds")
    else:
        recorded_at = pd.to_datetime(
            frame[timestamp_column], format="mixed", utc=True, errors="coerce"
        )
    values = pd.to_numeric(frame[value_column], errors="coerce")

    if "variable" in frame.columns:
        variables = frame["variable"].astype("string").str.strip().replace("", pd.NA)
        variables = variables.fillna(default_variable)
    else:
        variables = pd.Series(default_variable, index=frame.index, dtype="string")

    if "unit" in frame.columns:
        units = frame["unit"].astype("string").str.strip().replace("", pd.NA)
    else:
        units = pd.Series(pd.NA, index=frame.index, dtype="string")
    if default_unit:
        units = units.fillna(default_unit)

    working = pd.DataFrame(
        {
            "recorded_at": recorded_at,
            "value": values,
            "variable": variables,
            "unit": units,
        }
    )

    valid_mask = working["recorded_at"].notna() & working["value"].notna()
    rejected_rows = int((~valid_mask).sum())
    working = working.loc[valid_mask].copy()

    if working.empty:
        raise UnprocessableError(
            "No valid rows after validation",
            {"rows_read": raw_rows, "rejected_rows": rejected_rows},
        )

    before_dedup = len(working)
    working = working.drop_duplicates(subset=["variable", "recorded_at"], keep="last")
    duplicates_removed = before_dedup - len(working)
    if duplicates_removed:
        warnings.append(
            f"{duplicates_removed} duplicate (variable, timestamp) rows kept the last value"
        )

    working = working.sort_values(["variable", "recorded_at"]).reset_index(drop=True)
    working["is_outlier"] = _flag_outliers(working)

    records = [
        {
            "variable": str(variable),
            "recorded_at": timestamp.to_pydatetime(),
            "value": float(value),
            "unit": None if pd.isna(unit) else str(unit),
            "is_outlier": bool(is_outlier),
        }
        for variable, timestamp, value, unit, is_outlier in zip(
            working["variable"],
            working["recorded_at"],
            working["value"],
            working["unit"],
            working["is_outlier"],
            strict=True,
        )
    ]

    stats = {
        "rows_read": raw_rows,
        "rows_stored": len(working),
        "rows_rejected": rejected_rows,
        "duplicates_removed": duplicates_removed,
        "outliers_flagged": int(working["is_outlier"].sum()),
        "variables": _variable_stats(working),
        "time_range": {
            "start": working["recorded_at"].min().isoformat(),
            "end": working["recorded_at"].max().isoformat(),
        },
        "checksum_sha256": checksum,
        "source_filename": filename,
        "warnings": warnings,
    }

    return ETLResult(
        records=records,
        stats=stats,
        row_count=len(working),
        rejected_rows=rejected_rows,
        outlier_rows=int(working["is_outlier"].sum()),
        checksum_sha256=checksum,
        warnings=warnings,
    )


def _flag_outliers(frame: pd.DataFrame) -> pd.Series:
    """IQR rule per variable; groups with a zero IQR are never flagged."""
    grouped = frame.groupby("variable")["value"]
    q1 = grouped.transform(lambda series: series.quantile(0.25))
    q3 = grouped.transform(lambda series: series.quantile(0.75))
    iqr = q3 - q1
    low = q1 - IQR_FACTOR * iqr
    high = q3 + IQR_FACTOR * iqr
    flagged = (iqr > 0) & ((frame["value"] < low) | (frame["value"] > high))
    return flagged.fillna(False).astype(bool)


def _variable_stats(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for variable, group in frame.groupby("variable", sort=True):
        values = group["value"]
        stats[str(variable)] = {
            "count": int(values.size),
            "mean": float(values.mean()),
            "std": float(values.std(ddof=1)) if values.size > 1 else 0.0,
            "min": float(values.min()),
            "max": float(values.max()),
            "p05": float(values.quantile(0.05)),
            "p95": float(values.quantile(0.95)),
            "outliers": int(group["is_outlier"].sum()),
        }
    return stats


def create_dataset(
    session: Session,
    *,
    content: bytes,
    filename: str,
    name: str,
    variable: str = "value",
    unit: str | None = None,
    timestamp_column: str = "timestamp",
    value_column: str = "value",
) -> Dataset:
    """Run the ETL pipeline and persist the dataset plus its measurements."""
    result = process_csv(
        content,
        filename=filename,
        timestamp_column=timestamp_column,
        value_column=value_column,
        default_variable=variable,
        default_unit=unit,
    )

    dataset = Dataset(
        name=name,
        source_filename=filename,
        checksum_sha256=result.checksum_sha256,
        row_count=result.row_count,
        rejected_rows=result.rejected_rows,
        outlier_rows=result.outlier_rows,
        status="ready",
        stats=result.stats,
    )
    session.add(dataset)
    session.flush()

    for start in range(0, len(result.records), CHUNK_SIZE):
        batch = [
            {"dataset_id": dataset.id, **record}
            for record in result.records[start : start + CHUNK_SIZE]
        ]
        session.execute(insert(Measurement), batch)

    session.commit()
    session.refresh(dataset)
    return dataset


def get_dataset(session: Session, dataset_id: UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    return dataset


def list_datasets(
    session: Session, *, limit: int = 20, offset: int = 0
) -> tuple[list[Dataset], int]:
    total = int(session.scalar(select(func.count()).select_from(Dataset)) or 0)
    items = list(
        session.scalars(
            select(Dataset)
            .order_by(Dataset.created_at.desc(), Dataset.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total


def delete_dataset(session: Session, dataset_id: UUID) -> None:
    result = session.execute(delete(Dataset).where(Dataset.id == dataset_id))
    if result.rowcount == 0:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    session.commit()


def list_measurements(
    session: Session,
    dataset_id: UUID,
    *,
    variable: str | None = None,
    only_outliers: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Measurement], int]:
    get_dataset(session, dataset_id)

    filters = [Measurement.dataset_id == dataset_id]
    if variable is not None:
        filters.append(Measurement.variable == variable)
    if only_outliers:
        filters.append(Measurement.is_outlier.is_(True))

    total = int(session.scalar(select(func.count()).select_from(Measurement).where(*filters)) or 0)
    items = list(
        session.scalars(
            select(Measurement)
            .where(*filters)
            .order_by(Measurement.variable, Measurement.recorded_at)
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total


def dataset_stats(session: Session, dataset_id: UUID) -> dict[str, Any]:
    """Recompute aggregate statistics with SQL (not from the stored JSON)."""
    dataset = get_dataset(session, dataset_id)

    rows = session.execute(
        select(
            Measurement.variable,
            func.count().label("count"),
            func.avg(Measurement.value).label("mean"),
            func.stddev_samp(Measurement.value).label("std"),
            func.min(Measurement.value).label("minimum"),
            func.max(Measurement.value).label("maximum"),
            func.sum(case((Measurement.is_outlier.is_(True), 1), else_=0)).label("outliers"),
        )
        .where(Measurement.dataset_id == dataset_id)
        .group_by(Measurement.variable)
        .order_by(Measurement.variable)
    ).all()

    variables = [
        {
            "variable": row.variable,
            "count": int(row.count),
            "mean": float(row.mean) if row.mean is not None else None,
            "std": float(row.std) if row.std is not None else None,
            "minimum": float(row.minimum) if row.minimum is not None else None,
            "maximum": float(row.maximum) if row.maximum is not None else None,
            "outliers": int(row.outliers or 0),
        }
        for row in rows
    ]

    return {
        "dataset_id": dataset.id,
        "row_count": dataset.row_count,
        "rejected_rows": dataset.rejected_rows,
        "outlier_rows": dataset.outlier_rows,
        "variables": variables,
        "stored_stats": dataset.stats,
    }
