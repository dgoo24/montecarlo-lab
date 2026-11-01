"""Domain exceptions and their HTTP mapping.

Services raise these errors; the API layer never has to translate database or
ETL failures by hand.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    status_code: int = 400

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class UnprocessableError(AppError):
    status_code = 422


class PayloadTooLargeError(AppError):
    status_code = 413


class SimulationExecutionError(AppError):
    status_code = 500


def register_exception_handlers(app: FastAPI) -> None:
    """Attach JSON handlers for every ``AppError`` subclass."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        payload: dict[str, Any] = {"detail": exc.message}
        if exc.details:
            payload["context"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=payload)
