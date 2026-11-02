"""Monte Carlo simulation endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.common import Page
from app.schemas.simulations import (
    Histogram,
    SimulationCreate,
    SimulationPathRead,
    SimulationRead,
    SimulationResults,
    SimulationTrajectories,
)
from app.services import simulations as service

router = APIRouter(prefix="/simulations", tags=["simulations"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=SimulationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Run a Monte Carlo simulation and persist its results",
)
def create_simulation(payload: SimulationCreate, db: DbSession) -> SimulationRead:
    run = service.create_and_run(db, payload)
    return SimulationRead.model_validate(run)


@router.get("", response_model=Page[SimulationRead], summary="List simulation runs")
def list_simulations(
    db: DbSession,
    run_status: Annotated[
        str | None,
        Query(alias="status", pattern="^(pending|running|completed|failed)$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SimulationRead]:
    items, total = service.list_runs(db, status=run_status, limit=limit, offset=offset)
    return Page[SimulationRead](
        items=[SimulationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=SimulationRead, summary="Fetch a simulation run")
def get_simulation(run_id: UUID, db: DbSession) -> SimulationRead:
    return SimulationRead.model_validate(service.get_run(db, run_id))


@router.get(
    "/{run_id}/results",
    response_model=SimulationResults,
    summary="Summary statistics and a sample of terminal values",
)
def get_simulation_results(
    run_id: UUID,
    db: DbSession,
    sample: Annotated[int, Query(ge=1, le=5_000, description="Terminal values to return")] = 200,
) -> SimulationResults:
    run, values, total = service.get_results(db, run_id, sample_limit=sample)
    return SimulationResults(
        run=SimulationRead.model_validate(run),
        terminal_values=values,
        returned=len(values),
        total_paths=total,
    )


@router.get(
    "/{run_id}/paths",
    response_model=Page[SimulationPathRead],
    summary="Page through per-path terminal statistics",
)
def get_simulation_paths(
    run_id: UUID,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SimulationPathRead]:
    items, total = service.get_path_page(db, run_id, limit=limit, offset=offset)
    return Page[SimulationPathRead](
        items=[SimulationPathRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{run_id}/histogram",
    response_model=Histogram,
    summary="Histogram of terminal values",
)
def get_simulation_histogram(run_id: UUID, db: DbSession) -> Histogram:
    run = service.get_run(db, run_id)
    return Histogram.model_validate(service.get_histogram(run))


@router.get(
    "/{run_id}/trajectories",
    response_model=SimulationTrajectories,
    summary="Bounded preview of the simulated paths (for charts)",
)
def get_simulation_trajectories(run_id: UUID, db: DbSession) -> SimulationTrajectories:
    run = service.get_run(db, run_id)
    return SimulationTrajectories.model_validate(service.get_trajectories(run))


@router.delete(
    "/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a simulation and its paths",
)
def delete_simulation(run_id: UUID, db: DbSession) -> Response:
    service.delete_run(db, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
