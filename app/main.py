"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import __version__
from app.api.routes import datasets, health, overview, simulations
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import engine

logger = logging.getLogger(__name__)

DESCRIPTION = """
Backend for running Monte Carlo simulations over stochastic models, persisting
every run in PostgreSQL, and ingesting experimental measurements through a
validated Pandas ETL pipeline.

* **Simulations**: GBM, Ornstein-Uhlenbeck and static normal uncertainty.
  Every run is reproducible given its seed and can be queried by id.
* **Datasets**: CSV upload with schema validation, de-duplication and IQR
  outlier flagging.
* **Operations**: liveness/readiness probes and aggregate metrics.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    logger.info("Starting %s in %s mode", settings.app_name, settings.environment)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database is not reachable at startup")
        raise
    yield
    engine.dispose()
    logger.info("Application stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "simulations", "description": "Monte Carlo runs and results"},
            {"name": "datasets", "description": "Experimental data ingestion (ETL)"},
            {"name": "overview", "description": "Aggregate metrics"},
            {"name": "health", "description": "Liveness and readiness"},
        ],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(simulations.router, prefix="/api/v1")
    app.include_router(datasets.router, prefix="/api/v1")
    app.include_router(overview.router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    def index() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    return app


app = create_app()
