"""Platform-wide metrics, useful for a dashboard or an ops check."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import Dataset, Measurement, SimulationRun
from app.schemas.datasets import Overview

router = APIRouter(tags=["overview"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/overview", response_model=Overview, summary="Aggregate platform metrics")
def overview(db: DbSession) -> Overview:
    simulations_total = int(db.scalar(select(func.count()).select_from(SimulationRun)) or 0)
    simulations_completed = int(
        db.scalar(
            select(func.count())
            .select_from(SimulationRun)
            .where(SimulationRun.status == "completed")
        )
        or 0
    )
    paths_simulated = int(
        db.scalar(
            select(func.coalesce(func.sum(SimulationRun.n_paths), 0)).where(
                SimulationRun.status == "completed"
            )
        )
        or 0
    )
    avg_duration = db.scalar(
        select(func.avg(SimulationRun.duration_ms)).where(SimulationRun.status == "completed")
    )
    datasets_total = int(db.scalar(select(func.count()).select_from(Dataset)) or 0)
    measurements_total = int(db.scalar(select(func.count()).select_from(Measurement)) or 0)

    return Overview(
        simulations_total=simulations_total,
        simulations_completed=simulations_completed,
        paths_simulated=paths_simulated,
        avg_duration_ms=float(avg_duration) if avg_duration is not None else None,
        datasets_total=datasets_total,
        measurements_total=measurements_total,
    )
