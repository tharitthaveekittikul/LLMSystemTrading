"""Request logging middleware.

Logs only what matters:
- 4xx/5xx responses (WARNING/ERROR) with method, path, status, duration
- Slow requests >500ms (WARNING)
- All requests at DEBUG when debug mode is on (handled by uvicorn.access instead)

Never logs request bodies or response bodies.
"""
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_SLOW_REQUEST_MS = 500
_SKIP_PATHS = {"/health", "/docs", "/openapi.json"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS or request.url.path.startswith("/ws"):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        status = response.status_code
        msg = "%s %s %d %.0fms"
        args = (request.method, request.url.path, status, duration_ms)

        if status >= 500:
            logger.error(msg, *args)
        elif status >= 400:
            logger.warning(msg, *args)
        elif duration_ms > _SLOW_REQUEST_MS:
            logger.warning("SLOW " + msg, *args)

        return response
