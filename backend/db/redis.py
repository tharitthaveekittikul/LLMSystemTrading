"""Redis client — shared async connection pool.

Used for caching (kill-switch state, rate-limit counters, indicator results)
and Pub/Sub (cross-worker WebSocket fan-out).
"""
import json as _json
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


async def check_llm_rate_limit(
    account_id: int,
    max_calls: int = 10,
    window_seconds: int = 60,
) -> bool:
    """Increment the LLM call counter for account_id.

    Returns True if the call is allowed; False if the rate limit is exceeded.
    Uses Redis INCR + EXPIRE (set TTL only on first increment of the window).
    """
    r = get_redis()
    key = f"llm_rate:{account_id}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, window_seconds)
    return count <= max_calls


async def get_candle_cache(account_id: int, symbol: str, timeframe: str) -> list | None:
    """Return cached OHLCV candles or None on cache miss."""
    r = get_redis()
    key = f"ohlcv:{account_id}:{symbol}:{timeframe}"
    raw = await r.get(key)
    if raw is None:
        return None
    return _json.loads(raw)


async def set_candle_cache(
    account_id: int,
    symbol: str,
    timeframe: str,
    candles: list,
    ttl_seconds: int,
) -> None:
    """Store OHLCV candles as JSON string with a TTL."""
    r = get_redis()
    key = f"ohlcv:{account_id}:{symbol}:{timeframe}"
    await r.set(key, _json.dumps(candles, default=str), ex=ttl_seconds)
