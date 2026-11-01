"""Liveness and readiness endpoints (outside the versioned API)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import get_db
from app.core.config import get_settings
from app.schemas.common import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", environment=settings.environment, version=__version__)


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
def readiness(db: Session = Depends(get_db)) -> ReadinessResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Readiness check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not reachable",
        ) from exc
    return ReadinessResponse(status="ready", database="up")
