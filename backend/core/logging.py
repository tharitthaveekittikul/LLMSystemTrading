"""Centralized logging configuration.

Call setup_logging() once at application startup (from main.py).
All other modules obtain their logger via:

    import logging
    logger = logging.getLogger(__name__)
"""
import logging
import sys

from core.config import settings

_LEVEL_COLORS = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # green
    "WARNING":  "\033[33m",   # yellow
    "ERROR":    "\033[31m",   # red
    "CRITICAL": "\033[35m",   # magenta
}
_RESET = "\033[0m"
_DIM   = "\033[2m"


class _ColorFormatter(logging.Formatter):
    """Colorizes levelname and dims the logger name; plain text otherwise."""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        color = _LEVEL_COLORS.get(record.levelname, "")
        # Replace the plain levelname with a colored one
        plain_level = f"{record.levelname:<8}"
        colored_level = f"{color}{plain_level}{_RESET}"
        line = line.replace(plain_level, colored_level, 1)
        # Dim the logger name (name: portion after the level)
        name_tag = f"{record.name}:"
        line = line.replace(name_tag, f"{_DIM}{name_tag}{_RESET}", 1)
        return line

_NOISY_LOGGERS = [
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "uvicorn.access",
    "httpx",
]

# Uvicorn loggers that install their own handlers with a different format.
# We strip those handlers and let logs propagate to our root formatter.
_UVICORN_LOGGERS = ["uvicorn", "uvicorn.error", "uvicorn.access"]


def setup_logging() -> None:
    """Configure the root logger.  Safe to call multiple times (idempotent)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"
    use_color = sys.stdout.isatty()
    formatter = _ColorFormatter(fmt, datefmt=datefmt) if use_color else logging.Formatter(fmt, datefmt=datefmt)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party loggers in all modes
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # In debug mode, show uvicorn access logs (one line per request)
    if settings.debug:
        logging.getLogger("uvicorn.access").setLevel(logging.DEBUG)


def fix_uvicorn_logging() -> None:
    """Remove uvicorn's own handlers so all uvicorn logs use our root formatter.

    Uvicorn calls logging.config.dictConfig() during startup — after setup_logging()
    runs — which installs its own handlers with a different format and sets
    propagate=False.  Call this function from the ASGI lifespan (after uvicorn has
    finished its own log config) to restore consistent formatting.
    """
    for name in _UVICORN_LOGGERS:
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

    # Re-apply level rules that setup_logging() already set on the root pass.
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    if settings.debug:
        logging.getLogger("uvicorn.access").setLevel(logging.DEBUG)
