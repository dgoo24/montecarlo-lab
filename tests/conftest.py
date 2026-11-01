"""Shared test configuration.

Integration tests run against a real PostgreSQL database migrated with Alembic.
The database name **must** end with ``_test``: the session fixture drops and
recreates the ``public`` schema, so pointing it at a development database would
destroy data.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault(
    "MC_DATABASE_URL",
    "postgresql+psycopg://montecarlo:montecarlo@localhost:5432/montecarlo_test",
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402

TABLES = "measurements, datasets, simulation_paths, simulation_runs"


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Drop the test schema and apply every migration."""
    database = engine.url.database or ""
    if not database.endswith("_test"):
        pytest.exit(
            f"Refusing to run destructive tests against '{database}'. "
            "Set MC_DATABASE_URL to a database whose name ends with '_test'.",
            returncode=1,
        )

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    command.upgrade(config, "head")


@pytest.fixture
def client(migrated_database: None) -> TestClient:
    """A TestClient with an empty database for each test."""
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))

    with TestClient(app) as test_client:
        yield test_client
