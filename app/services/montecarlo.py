"""Monte Carlo engines.

All generators are fully vectorised with NumPy and use ``numpy.random.Generator``
so a given ``(params, n_paths, n_steps, seed)`` tuple always yields the same
result. That reproducibility is what makes the persisted runs auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.schemas.simulations import GbmParams, NormalParams, OuParams, SimulationParams

HISTOGRAM_BINS = 24
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)
MAX_SAMPLE_PATHS = 25
MAX_SAMPLE_STEPS = 300


@dataclass(frozen=True, slots=True)
class SimulationOutput:
    """Raw output of a simulation: full paths plus derived statistics."""

    paths: np.ndarray
    terminal_values: np.ndarray
    summary: dict[str, Any]


def simulate(
    params: SimulationParams,
    *,
    n_paths: int,
    n_steps: int,
    seed: int | None = None,
    threshold: float | None = None,
) -> SimulationOutput:
    """Generate paths for ``params`` and summarise their terminal values."""
    rng = np.random.default_rng(seed)

    if isinstance(params, GbmParams):
        paths = _geometric_brownian_motion(params, n_paths, n_steps, rng)
    elif isinstance(params, OuParams):
        paths = _ornstein_uhlenbeck(params, n_paths, n_steps, rng)
    elif isinstance(params, NormalParams):
        paths = _normal(params, n_paths, rng)
    else:  # pragma: no cover - guarded by the pydantic discriminated union
        raise TypeError(f"Unsupported model: {type(params).__name__}")

    terminal = paths[:, -1]
    return SimulationOutput(
        paths=paths,
        terminal_values=terminal,
        summary=summarise(terminal, threshold),
    )


def _geometric_brownian_motion(
    params: GbmParams,
    n_paths: int,
    n_steps: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Exact GBM discretisation in log space: S_t = S_0 * exp(...)."""
    dt = params.dt
    shocks = rng.standard_normal((n_paths, n_steps))
    log_increments = (params.mu - 0.5 * params.sigma**2) * dt
    log_increments += params.sigma * np.sqrt(dt) * shocks

    log_paths = np.zeros((n_paths, n_steps + 1), dtype=np.float64)
    log_paths[:, 1:] = np.cumsum(log_increments, axis=1)
    return params.s0 * np.exp(log_paths)


def _ornstein_uhlenbeck(
    params: OuParams,
    n_paths: int,
    n_steps: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Exact AR(1) representation of the OU process."""
    dt = params.dt
    decay = np.exp(-params.theta * dt)
    shock_scale = params.sigma * np.sqrt((1 - np.exp(-2 * params.theta * dt)) / (2 * params.theta))
    shocks = rng.standard_normal((n_paths, n_steps))

    paths = np.empty((n_paths, n_steps + 1), dtype=np.float64)
    paths[:, 0] = params.x0
    drift = params.mu * (1 - decay)
    for step in range(n_steps):
        paths[:, step + 1] = paths[:, step] * decay + drift + shock_scale * shocks[:, step]
    return paths


def _normal(
    params: NormalParams,
    n_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Static uncertainty propagation: one draw per path."""
    shocks = rng.standard_normal((n_paths, 1))
    return params.mean + params.std * shocks


def sample_trajectories(paths: np.ndarray) -> dict[str, Any]:
    """Downsample full paths to a bounded preview for charts.

    The response keeps at most ``MAX_SAMPLE_PATHS`` paths and
    ``MAX_SAMPLE_STEPS`` points per path, which caps the JSONB payload at a few
    tens of kilobytes regardless of the run size.
    """
    n_paths, n_points = paths.shape
    path_index = np.linspace(0, n_paths - 1, min(MAX_SAMPLE_PATHS, n_paths), dtype=int)
    step_index = np.linspace(0, n_points - 1, min(MAX_SAMPLE_STEPS, n_points), dtype=int)
    sample = paths[np.ix_(path_index, step_index)]

    return {
        "steps": [int(step) for step in step_index],
        "paths": [[float(f"{value:.6g}") for value in row] for row in sample],
    }


def summarise(values: np.ndarray, threshold: float | None) -> dict[str, Any]:
    """Compute the statistics persisted for every run."""
    p05, p25, p50, p75, p95 = (float(q) for q in np.quantile(values, QUANTILES))
    counts, edges = np.histogram(values, bins=HISTOGRAM_BINS)
    tail = values[values <= p05]

    return {
        "mean": float(np.mean(values)),
        "std": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
        "minimum": float(np.min(values)),
        "maximum": float(np.max(values)),
        "p05": p05,
        "p25": p25,
        "p50": p50,
        "p75": p75,
        "p95": p95,
        "var_95": p05,
        "expected_shortfall_95": float(np.mean(tail)) if tail.size else p05,
        "prob_above_threshold": (None if threshold is None else float(np.mean(values > threshold))),
        "histogram": {
            "bins": [float(edge) for edge in edges],
            "counts": [int(count) for count in counts],
        },
    }
