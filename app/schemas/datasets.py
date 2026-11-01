"""Request/response schemas for datasets."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    source_filename: str
    checksum_sha256: str
    row_count: int
    rejected_rows: int
    outlier_rows: int
    status: str
    error: str | None
    stats: dict | None
    created_at: datetime


class MeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variable: str
    recorded_at: datetime
    value: float
    unit: str | None
    is_outlier: bool


class VariableStats(BaseModel):
    variable: str
    count: int
    mean: float | None
    std: float | None
    minimum: float | None
    maximum: float | None
    outliers: int


class DatasetStats(BaseModel):
    dataset_id: UUID
    row_count: int
    rejected_rows: int
    outlier_rows: int
    variables: list[VariableStats]
    stored_stats: dict | None


class Overview(BaseModel):
    simulations_total: int
    simulations_completed: int
    paths_simulated: int
    avg_duration_ms: float | None
    datasets_total: int
    measurements_total: int
