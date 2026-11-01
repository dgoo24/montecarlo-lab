"""Generate a synthetic experimental dataset with realistic quality issues.

The generated CSV intentionally contains duplicates, missing values, an
unparseable timestamp and a few outliers, so the ETL pipeline has something to
clean and report on.

Usage:
    python scripts/generate_sample_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "sample_measurements.csv"

PERIODS = 24 * 30  # one month of hourly readings
SEED = 20240501


def main() -> None:
    rng = np.random.default_rng(SEED)
    timestamps = pd.date_range("2024-05-01", periods=PERIODS, freq="h", tz="UTC")
    hours = np.arange(PERIODS)

    temperature = 20 + 3 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, 0.25, PERIODS)
    pressure = 1.013 + 0.015 * np.sin(2 * np.pi * hours / 12 + 1) + rng.normal(0, 0.003, PERIODS)

    frame = pd.concat(
        [
            pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "variable": "reactor_temperature",
                    "value": temperature,
                    "unit": "degC",
                }
            ),
            pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "variable": "reactor_pressure",
                    "value": pressure,
                    "unit": "bar",
                }
            ),
        ],
        ignore_index=True,
    ).sort_values(["timestamp", "variable"], ignore_index=True)

    # Sensor spikes: preserve them so the ETL can flag them as outliers.
    def bump(variable: str, position: int, delta: float) -> None:
        index = frame.index[frame["variable"] == variable][position]
        frame.loc[index, "value"] += delta

    bump("reactor_temperature", 100, 14.0)
    bump("reactor_temperature", 400, -12.0)
    bump("reactor_pressure", 300, 0.09)
    bump("reactor_pressure", 600, -0.08)

    # Duplicated readings (same variable and timestamp).
    duplicates = frame.iloc[[10, 900]].copy()
    frame = pd.concat([frame, duplicates], ignore_index=True)

    # Missing measurements.
    frame.loc[30, "value"] = np.nan
    frame.loc[31, "value"] = np.nan

    frame = frame.sort_values(["timestamp", "variable"], ignore_index=True)

    # A corrupt row that must be rejected, not silently repaired.
    corrupt = pd.DataFrame(
        [
            {
                "timestamp": "not-a-timestamp",
                "variable": "reactor_temperature",
                "value": 20.0,
                "unit": "degC",
            }
        ]
    )
    frame = pd.concat([frame, corrupt], ignore_index=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT, index=False)
    print(f"Wrote {len(frame):,} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
