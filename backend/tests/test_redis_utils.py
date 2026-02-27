import json
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_check_llm_rate_limit_allows_first_call():
    """First call within window returns True (allowed)."""
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 1  # first call
    mock_redis.expire = AsyncMock()
    with patch("db.redis.get_redis", return_value=mock_redis):
        from db.redis import check_llm_rate_limit
        result = await check_llm_rate_limit(account_id=1)
    assert result is True
    mock_redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_check_llm_rate_limit_blocks_over_limit():
    """Call count exceeding max returns False (blocked)."""
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 11  # over the 10-call limit
    mock_redis.expire = AsyncMock()
    with patch("db.redis.get_redis", return_value=mock_redis):
        from db.redis import check_llm_rate_limit
        result = await check_llm_rate_limit(account_id=1, max_calls=10)
    assert result is False


@pytest.mark.asyncio
async def test_candle_cache_miss_returns_none():
    """Cache miss returns None."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    with patch("db.redis.get_redis", return_value=mock_redis):
        from db.redis import get_candle_cache
        result = await get_candle_cache(1, "EURUSD", "M15")
    assert result is None


@pytest.mark.asyncio
async def test_candle_cache_hit_returns_list():
    """Cache hit returns deserialized candle list."""
    candles = [{"time": "2025-01-01", "open": 1.1, "close": 1.2}]
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(candles)
    with patch("db.redis.get_redis", return_value=mock_redis):
        from db.redis import get_candle_cache
        result = await get_candle_cache(1, "EURUSD", "M15")
    assert result == candles
