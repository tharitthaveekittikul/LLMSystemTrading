"""Tests for storage API — Redis section."""
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from api.routes import storage

_test_app = FastAPI()
_test_app.include_router(storage.router, prefix="/api/v1/storage")


@pytest.mark.asyncio
async def test_redis_info_returns_shape():
    mock_redis = AsyncMock()
    mock_redis.info = AsyncMock(return_value={
        "used_memory_human": "1.50M",
        "connected_clients": 3,
        "uptime_in_seconds": 3600,
        "redis_version": "7.0.15",
        "keyspace_hits": 100,
        "keyspace_misses": 10,
    })
    mock_redis.dbsize = AsyncMock(return_value=5)

    with patch("api.routes.storage.get_redis", return_value=mock_redis):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/redis/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "7.0.15"
    assert data["key_count"] == 5
    assert "memory_used" in data


@pytest.mark.asyncio
async def test_redis_unreachable_returns_503():
    mock_redis = AsyncMock()
    mock_redis.info = AsyncMock(side_effect=Exception("connection refused"))

    with patch("api.routes.storage.get_redis", return_value=mock_redis):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/redis/info")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_redis_flush_calls_flushdb():
    mock_redis = AsyncMock()
    mock_redis.dbsize = AsyncMock(return_value=7)
    mock_redis.flushdb = AsyncMock(return_value=True)

    with patch("api.routes.storage.get_redis", return_value=mock_redis):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/v1/storage/redis/flush")
    assert resp.status_code == 200
    data = resp.json()
    assert data["keys_flushed"] == 7
    mock_redis.flushdb.assert_awaited_once()
