"""Dataset ingestion and exploration endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.common import Page
from app.schemas.datasets import DatasetRead, DatasetStats, MeasurementRead
from app.services import etl

router = APIRouter(prefix="/datasets", tags=["datasets"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=DatasetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV, validate it and store the measurements",
)
def upload_dataset(
    db: DbSession,
    file: Annotated[UploadFile, File(description="Experimental data in CSV format")],
    name: Annotated[str, Form(min_length=1, max_length=200)],
    variable: Annotated[
        str, Form(min_length=1, max_length=80, description="Fallback variable name")
    ] = "value",
    unit: Annotated[str | None, Form(max_length=32)] = None,
    timestamp_column: Annotated[str, Form(max_length=80)] = "timestamp",
    value_column: Annotated[str, Form(max_length=80)] = "value",
) -> DatasetRead:
    content = file.file.read()
    dataset = etl.create_dataset(
        db,
        content=content,
        filename=file.filename or "upload.csv",
        name=name,
        variable=variable,
        unit=unit,
        timestamp_column=timestamp_column,
        value_column=value_column,
    )
    return DatasetRead.model_validate(dataset)


@router.get("", response_model=Page[DatasetRead], summary="List datasets")
def list_datasets(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DatasetRead]:
    items, total = etl.list_datasets(db, limit=limit, offset=offset)
    return Page[DatasetRead](
        items=[DatasetRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}", response_model=DatasetRead, summary="Fetch a dataset")
def get_dataset(dataset_id: UUID, db: DbSession) -> DatasetRead:
    return DatasetRead.model_validate(etl.get_dataset(db, dataset_id))


@router.get(
    "/{dataset_id}/stats",
    response_model=DatasetStats,
    summary="Aggregate statistics recomputed from the stored measurements",
)
def get_dataset_stats(dataset_id: UUID, db: DbSession) -> DatasetStats:
    return DatasetStats.model_validate(etl.dataset_stats(db, dataset_id))


@router.get(
    "/{dataset_id}/measurements",
    response_model=Page[MeasurementRead],
    summary="Page through measurements",
)
def list_measurements(
    dataset_id: UUID,
    db: DbSession,
    variable: Annotated[str | None, Query(max_length=80)] = None,
    only_outliers: bool = False,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MeasurementRead]:
    items, total = etl.list_measurements(
        db,
        dataset_id,
        variable=variable,
        only_outliers=only_outliers,
        limit=limit,
        offset=offset,
    )
    return Page[MeasurementRead](
        items=[MeasurementRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dataset and its measurements",
)
def delete_dataset(dataset_id: UUID, db: DbSession) -> Response:
    etl.delete_dataset(db, dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
