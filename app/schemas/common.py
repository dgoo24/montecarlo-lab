"""Shared response schemas."""

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    """A paginated collection."""

    items: list[T]
    total: int = Field(description="Total number of matching records")
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
