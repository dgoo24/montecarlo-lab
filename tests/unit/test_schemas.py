"""Unit tests for request validation rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.simulations import SimulationCreate


def payload(**overrides):
    data = {
        "name": "test run",
        "params": {"kind": "gbm", "s0": 100.0, "mu": 0.05, "sigma": 0.2},
        "n_paths": 500,
        "n_steps": 100,
        "seed": 7,
    }
    data.update(overrides)
    return data


def test_accepts_valid_payload() -> None:
    model = SimulationCreate.model_validate(payload())
    assert model.params.kind == "gbm"
    assert model.n_paths == 500


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_paths": 10},
        {"n_paths": 20_000, "n_steps": 5_000},  # exceeds max cells
        {"n_steps": 50_001},
        {"seed": -1},
        {"name": ""},
        {"params": {"kind": "gbm", "s0": 100.0, "mu": 0.05, "sigma": -0.2}},
        {"params": {"kind": "unknown", "value": 1}},
    ],
)
def test_rejects_invalid_payloads(overrides) -> None:
    with pytest.raises(ValidationError):
        SimulationCreate.model_validate(payload(**overrides))


def test_discriminated_union_selects_model() -> None:
    model = SimulationCreate.model_validate(
        payload(params={"kind": "ou", "x0": 1.0, "mu": 0.0, "theta": 1.0, "sigma": 0.5})
    )
    assert model.params.kind == "ou"
