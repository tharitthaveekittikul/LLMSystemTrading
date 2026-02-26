"""Centralized logging configuration.

Call setup_logging() once at application startup (from main.py).
All other modules obtain their logger via:

    import logging
    logger = logging.getLogger(__name__)
"""
import logging
import sys

from core.config import settings

_NOISY_LOGGERS = [
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "uvicorn.access",
    "httpx",
]


def setup_logging() -> None:
    """Configure the root logger.  Safe to call multiple times (idempotent)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    # Suppress noisy third-party loggers unless in debug mode
    if not settings.debug:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
