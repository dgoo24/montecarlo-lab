"""Logging helpers."""

import logging

from app.core.config import get_settings

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s :: %(message)s"


def configure_logging() -> None:
    """Configure root logging once, at application startup."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format=_FORMAT,
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        force=True,
    )
