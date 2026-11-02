"""Request/response schemas for simulations.

The stochastic model is a discriminated union: the ``kind`` field selects the
parameter set and therefore the generator used. Pydantic validates each set
(e.g. ``sigma > 0``) before the request reaches the service layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import get_settings


class GbmParams(BaseModel):
    """Geometric Brownian Motion, the standard model for multiplicative growth."""

    kind: Literal["gbm"] = "gbm"
    s0: float = Field(gt=0, description="Initial value")
    mu: float = Field(description="Annualised drift")
    sigma: float = Field(gt=0, le=5, description="Annualised volatility")
    dt: float = Field(default=1 / 252, gt=0, le=1, description="Time step, in years")


class OuParams(BaseModel):
    """Ornstein-Uhlenbeck process: mean-reverting noise around ``mu``."""

    kind: Literal["ou"] = "ou"
    x0: float = Field(description="Initial value")
    mu: float = Field(description="Long-run mean")
    theta: float = Field(gt=0, description="Mean-reversion speed")
    sigma: float = Field(gt=0, le=100, description="Volatility")
    dt: float = Field(default=1 / 252, gt=0, le=1, description="Time step")


class NormalParams(BaseModel):
    """Static uncertainty propagation: independent draws from N(mean, std^2)."""

    kind: Literal["normal"] = "normal"
    mean: float
    std: float = Field(gt=0)


SimulationParams = Annotated[
    GbmParams | OuParams | NormalParams,
    Field(discriminator="kind"),
]


class SimulationCreate(BaseModel):
    """Payload accepted by ``POST /api/v1/simulations``."""

    name: str = Field(min_length=1, max_length=200)
    params: SimulationParams
    n_paths: int = Field(default=1_000, ge=1, le=100_000)
    n_steps: int = Field(default=252, ge=1, le=50_000)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    threshold: float | None = Field(
        default=None, description="Optional target used to estimate P(X > threshold)"
    )

    @model_validator(mode="after")
    def _enforce_workload_limits(self) -> SimulationCreate:
        settings = get_settings()
        if self.n_paths < 100:
            raise ValueError("n_paths must be at least 100")
        if self.n_paths > settings.max_paths:
            raise ValueError(f"n_paths cannot exceed {settings.max_paths}")
        if self.n_steps > settings.max_steps:
            raise ValueError(f"n_steps cannot exceed {settings.max_steps}")
        cells = self.n_paths * self.n_steps
        if cells > settings.max_cells:
            raise ValueError(
                f"n_paths * n_steps cannot exceed {settings.max_cells} (requested {cells})"
            )
        return self


class Histogram(BaseModel):
    bins: list[float] = Field(description="Bin edges, length = len(counts) + 1")
    counts: list[int]


class SimulationSummary(BaseModel):
    mean: float
    std: float
    minimum: float
    maximum: float
    p05: float
    p25: float
    p50: float
    p75: float
    p95: float
    var_95: float = Field(description="5th percentile of terminal values")
    expected_shortfall_95: float = Field(description="Mean of the worst 5% of outcomes")
    prob_above_threshold: float | None = None
    histogram: Histogram


class SimulationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    model: str
    params: dict
    n_paths: int
    n_steps: int
    seed: int | None
    threshold: float | None
    status: str
    summary: SimulationSummary | None
    duration_ms: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class SimulationPathRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path_index: int
    terminal_value: float
    min_value: float
    max_value: float


class SimulationResults(BaseModel):
    run: SimulationRead
    terminal_values: list[float] = Field(description="Sample of terminal values, in path order")
    returned: int
    total_paths: int


class SimulationTrajectories(BaseModel):
    """Bounded preview of the simulated paths, suitable for charting."""

    run_id: UUID
    steps: list[int] = Field(description="Step indices kept in the preview")
    paths: list[list[float]] = Field(description="One list of values per sampled path")
    sampled_paths: int
    total_paths: int
    dt: float | None = Field(default=None, description="Time step, when the model defines one")
