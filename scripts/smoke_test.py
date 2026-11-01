"""End-to-end smoke test against a running API instance.

Exercises the three core flows: a Monte Carlo run, a dataset upload with the
ETL pipeline, and the aggregate metrics endpoint. Exits non-zero on failure,
so it doubles as a deployment gate in CI.

Usage:
    python scripts/smoke_test.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_measurements.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        ready = client.get("/health/ready")
        ready.raise_for_status()
        print(f"[ok] health        {ready.json()}")

        run = client.post(
            "/api/v1/simulations",
            json={
                "name": "Smoke test GBM",
                "params": {"kind": "gbm", "s0": 100.0, "mu": 0.07, "sigma": 0.25},
                "n_paths": 2_000,
                "n_steps": 252,
                "seed": 42,
                "threshold": 120.0,
            },
        )
        run.raise_for_status()
        run_body = run.json()
        summary = run_body["summary"]
        print(
            f"[ok] simulation    id={run_body['id']} status={run_body['status']} "
            f"p50={summary['p50']:.2f} p95={summary['p95']:.2f} "
            f"P(>120)={summary['prob_above_threshold']:.2%} "
            f"in {run_body['duration_ms']} ms"
        )

        results = client.get(f"/api/v1/simulations/{run_body['id']}/results?sample=5")
        results.raise_for_status()
        print(f"[ok] results       {results.json()['returned']} sampled terminal values")

        if not SAMPLE.exists():
            print(f"[!!] sample file missing: {SAMPLE}", file=sys.stderr)
            return 2

        dataset = client.post(
            "/api/v1/datasets",
            files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "text/csv")},
            data={"name": "Smoke test dataset"},
        )
        dataset.raise_for_status()
        dataset_body = dataset.json()
        print(
            f"[ok] dataset       id={dataset_body['id']} rows={dataset_body['row_count']} "
            f"rejected={dataset_body['rejected_rows']} outliers={dataset_body['outlier_rows']}"
        )

        stats = client.get(f"/api/v1/datasets/{dataset_body['id']}/stats")
        stats.raise_for_status()
        for item in stats.json()["variables"]:
            print(
                f"[ok] stats         {item['variable']}: n={item['count']} "
                f"mean={item['mean']:.4f} outliers={item['outliers']}"
            )

        overview = client.get("/api/v1/overview")
        overview.raise_for_status()
        print(f"[ok] overview      {overview.json()}")

    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
