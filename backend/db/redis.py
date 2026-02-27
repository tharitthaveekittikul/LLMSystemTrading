"""Redis client — shared async connection pool.

Used for caching (kill-switch state, rate-limit counters, indicator results)
and Pub/Sub (cross-worker WebSocket fan-out).
"""
import logging

from redis.asyncio import ConnectionPool, Redis

from core.config import settings

logger = logging.getLogger(__name__)

# Module-level pool — created eagerly at import time, reused across all coroutines.
# Mirrors the module-level engine pattern in db/postgres.py.
_pool = ConnectionPool.from_url(
    settings.redis_url,
    max_connections=20,
    decode_responses=True,
)


def get_redis() -> Redis:
    """Return a Redis client backed by the shared connection pool.

    The client does not own the pool — use without a context manager::

        r = get_redis()
        await r.set("key", "value")
        value = await r.get("key")
    """
    return Redis(connection_pool=_pool)


async def close_redis() -> None:
    """Drain and close the connection pool.

    Call once from the FastAPI lifespan shutdown block.
    """
    await _pool.aclose()
    logger.info("Redis connection pool closed")
