"""ORM models.

Schema notes
------------
* ``simulation_runs`` stores the job/request, ``simulation_paths`` the per-path
  terminal statistics. Keeping terminal values in rows (instead of a JSON blob)
  makes it cheap to page, index and aggregate them with SQL.
* ``measurements`` uses a long (tidy) layout so heterogeneous experimental
  variables share one table and one composite index.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SimulationRun(Base):
    """A Monte Carlo simulation request and its summary statistics."""

    __tablename__ = "simulation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    n_paths: Mapped[int] = mapped_column(Integer, nullable=False)
    n_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    threshold: Mapped[float | None] = mapped_column(Float)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Bounded preview of the trajectories (a few paths, downsampled steps) so a
    # UI can draw the series without persisting millions of floats per run.
    trajectory_sample: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paths: Mapped[list[SimulationPath]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SimulationPath(Base):
    """Terminal statistics for a single simulated path."""

    __tablename__ = "simulation_paths"
    __table_args__ = (Index("ix_simulation_paths_run_terminal", "run_id", "terminal_value"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), primary_key=True
    )
    path_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    terminal_value: Mapped[float] = mapped_column(Float, nullable=False)
    min_value: Mapped[float] = mapped_column(Float, nullable=False)
    max_value: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped[SimulationRun] = relationship(back_populates="paths")


class Dataset(Base):
    """An ingested experimental dataset (one CSV upload)."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outlier_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ready", server_default="ready", index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    measurements: Mapped[list[Measurement]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Measurement(Base):
    """One experimental observation in long format."""

    __tablename__ = "measurements"
    __table_args__ = (
        Index("ix_measurements_dataset_variable_time", "dataset_id", "variable", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    variable: Mapped[str] = mapped_column(String(80), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    is_outlier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    dataset: Mapped[Dataset] = relationship(back_populates="measurements")
