"""Simulation orchestration: run the engine, persist the run and read it back."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, SimulationExecutionError
from app.db.models import SimulationPath, SimulationRun
from app.schemas.simulations import SimulationCreate
from app.services import montecarlo

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"pending", "running", "completed", "failed"}


def create_and_run(session: Session, payload: SimulationCreate) -> SimulationRun:
    """Execute a simulation synchronously and store the result.

    The row is committed as ``running`` before the CPU-bound work starts, so a
    crash leaves an auditable record instead of an invisible failure.
    """
    run = SimulationRun(
        name=payload.name,
        model=payload.params.kind,
        params=payload.params.model_dump(),
        n_paths=payload.n_paths,
        n_steps=payload.n_steps,
        seed=payload.seed,
        threshold=payload.threshold,
        status="running",
    )
    session.add(run)
    session.commit()

    run_id = run.id
    started = time.perf_counter()
    try:
        output = montecarlo.simulate(
            payload.params,
            n_paths=payload.n_paths,
            n_steps=payload.n_steps,
            seed=payload.seed,
            threshold=payload.threshold,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        _persist_paths(session, run_id, output.paths, output.terminal_values)

        run = session.get(SimulationRun, run_id)
        if run is None:  # pragma: no cover - the row was committed above
            raise SimulationExecutionError(
                "The simulation row disappeared while running",
                {"simulation_id": str(run_id)},
            )
        run.summary = output.summary
        run.status = "completed"
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        session.commit()
        session.refresh(run)
        return run
    except Exception as exc:  # noqa: BLE001 - any failure must mark the run
        logger.exception("Simulation %s failed", run_id)
        session.rollback()
        _mark_failed(session, run_id, exc)
        raise SimulationExecutionError(
            "The simulation failed while executing the model",
            {"simulation_id": str(run_id), "error": str(exc)},
        ) from exc


def _persist_paths(
    session: Session,
    run_id: UUID,
    paths,
    terminal_values,
) -> None:
    rows = [
        {
            "run_id": run_id,
            "path_index": index,
            "terminal_value": float(terminal_values[index]),
            "min_value": float(paths[index].min()),
            "max_value": float(paths[index].max()),
        }
        for index in range(len(terminal_values))
    ]
    session.execute(insert(SimulationPath), rows)


def _mark_failed(session: Session, run_id: UUID, exc: Exception) -> None:
    run = session.get(SimulationRun, run_id)
    if run is None:  # pragma: no cover - only if the row vanished mid-flight
        return
    run.status = "failed"
    run.error = str(exc)[:2000]
    run.finished_at = datetime.now(UTC)
    session.commit()


def get_run(session: Session, run_id: UUID) -> SimulationRun:
    run = session.get(SimulationRun, run_id)
    if run is None:
        raise NotFoundError(f"Simulation {run_id} not found")
    return run


def list_runs(
    session: Session,
    *,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[SimulationRun], int]:
    if status is not None and status not in _VALID_STATUSES:
        raise ConflictError(f"Invalid status filter: {status}")

    stmt = select(SimulationRun)
    count_stmt = select(func.count()).select_from(SimulationRun)
    if status is not None:
        stmt = stmt.where(SimulationRun.status == status)
        count_stmt = count_stmt.where(SimulationRun.status == status)

    total = int(session.scalar(count_stmt) or 0)
    stmt = stmt.order_by(SimulationRun.created_at.desc(), SimulationRun.id.desc())
    items = list(session.scalars(stmt.limit(limit).offset(offset)))
    return items, total


def get_results(
    session: Session,
    run_id: UUID,
    *,
    sample_limit: int = 200,
) -> tuple[SimulationRun, list[float], int]:
    run = get_run(session, run_id)
    if run.status != "completed":
        raise ConflictError(f"Simulation {run_id} has no results (status={run.status})")

    values = session.scalars(
        select(SimulationPath.terminal_value)
        .where(SimulationPath.run_id == run_id)
        .order_by(SimulationPath.path_index)
        .limit(sample_limit)
    ).all()
    return run, [float(value) for value in values], run.n_paths


def get_path_page(
    session: Session,
    run_id: UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[SimulationPath], int]:
    run = get_run(session, run_id)
    if run.status != "completed":
        raise ConflictError(f"Simulation {run_id} has no results (status={run.status})")

    total = int(
        session.scalar(
            select(func.count()).select_from(SimulationPath).where(SimulationPath.run_id == run_id)
        )
        or 0
    )
    items = list(
        session.scalars(
            select(SimulationPath)
            .where(SimulationPath.run_id == run_id)
            .order_by(SimulationPath.path_index)
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total


def delete_run(session: Session, run_id: UUID) -> None:
    result = session.execute(delete(SimulationRun).where(SimulationRun.id == run_id))
    if result.rowcount == 0:
        raise NotFoundError(f"Simulation {run_id} not found")
    session.commit()
