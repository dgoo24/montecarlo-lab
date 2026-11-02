"""Unit tests for the Monte Carlo engines."""

from __future__ import annotations

import numpy as np
import pytest

from app.schemas.simulations import GbmParams, NormalParams, OuParams
from app.services.montecarlo import sample_trajectories, simulate, summarise


def test_gbm_paths_shape_and_positivity() -> None:
    result = simulate(
        GbmParams(s0=100.0, mu=0.05, sigma=0.2),
        n_paths=500,
        n_steps=60,
        seed=1,
    )

    assert result.paths.shape == (500, 61)
    assert result.terminal_values.shape == (500,)
    assert np.all(result.paths > 0)
    np.testing.assert_allclose(result.paths[:, 0], 100.0)


def test_same_seed_produces_identical_paths() -> None:
    params = GbmParams(s0=50.0, mu=0.0, sigma=0.3)

    first = simulate(params, n_paths=300, n_steps=40, seed=42)
    second = simulate(params, n_paths=300, n_steps=40, seed=42)
    other = simulate(params, n_paths=300, n_steps=40, seed=43)

    np.testing.assert_array_equal(first.paths, second.paths)
    assert not np.array_equal(first.paths, other.paths)


def test_gbm_terminal_mean_matches_analytic_expectation() -> None:
    params = GbmParams(s0=100.0, mu=0.1, sigma=0.25)
    result = simulate(params, n_paths=20_000, n_steps=252, seed=7)

    expected = params.s0 * np.exp(params.mu * params.dt * 252)
    assert result.terminal_values.mean() == pytest.approx(expected, rel=0.02)


def test_ornstein_uhlenbeck_reverts_to_long_run_mean() -> None:
    params = OuParams(x0=0.0, mu=10.0, theta=2.0, sigma=1.0, dt=0.05)
    result = simulate(params, n_paths=4_000, n_steps=400, seed=3)

    assert result.terminal_values.mean() == pytest.approx(10.0, abs=0.3)
    assert result.terminal_values.std() == pytest.approx(0.5, abs=0.15)


def test_normal_model_shape_and_moments() -> None:
    result = simulate(
        NormalParams(mean=5.0, std=2.0),
        n_paths=20_000,
        n_steps=1,
        seed=11,
    )

    assert result.paths.shape == (20_000, 1)
    assert result.terminal_values.mean() == pytest.approx(5.0, abs=0.1)
    assert result.terminal_values.std(ddof=1) == pytest.approx(2.0, abs=0.1)


def test_summary_contains_threshold_probability() -> None:
    result = simulate(
        NormalParams(mean=0.0, std=1.0),
        n_paths=10_000,
        n_steps=1,
        seed=5,
        threshold=0.0,
    )

    summary = result.summary
    assert summary["prob_above_threshold"] == pytest.approx(0.5, abs=0.03)
    assert summary["var_95"] < summary["p50"] < summary["p95"]
    assert summary["expected_shortfall_95"] <= summary["var_95"]
    assert summary["minimum"] <= summary["p05"]
    assert summary["p95"] <= summary["maximum"]
    assert len(summary["histogram"]["counts"]) == 24
    assert len(summary["histogram"]["bins"]) == 25
    assert sum(summary["histogram"]["counts"]) == 10_000


def test_summary_without_threshold_returns_none() -> None:
    summary = summarise(np.array([1.0, 2.0, 3.0]), None)
    assert summary["prob_above_threshold"] is None
    assert summary["mean"] == pytest.approx(2.0)


def test_sample_trajectories_is_bounded() -> None:
    sample = sample_trajectories(np.ones((1_000, 2_000)))

    assert len(sample["paths"]) == 25
    assert all(len(row) == 300 for row in sample["paths"])
    assert len(sample["steps"]) == 300
    assert sample["steps"][0] == 0
    assert sample["steps"][-1] == 1_999


def test_sample_trajectories_keeps_small_runs_untouched() -> None:
    sample = sample_trajectories(np.arange(15).reshape(3, 5))

    assert sample["steps"] == [0, 1, 2, 3, 4]
    assert len(sample["paths"]) == 3
    assert sample["paths"][1] == [5.0, 6.0, 7.0, 8.0, 9.0]
