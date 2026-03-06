"""Tests for storage API — QuestDB section."""
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from api.routes import storage

# Build a minimal test app (same pattern as Task 1 tests)
_test_app = FastAPI()
_test_app.include_router(storage.router, prefix="/api/v1/storage")


@pytest.mark.asyncio
async def test_questdb_tables_returns_list():
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1000)
    mock_conn.close = AsyncMock()

    with (
        patch(
            "api.routes.storage._questdb_list_tables",
            new=AsyncMock(return_value=["equity_snapshots", "ohlcv_eurusd_m15"]),
        ),
        patch("api.routes.storage.questdb_get_conn", return_value=mock_conn),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/questdb/tables")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"] == "equity_snapshots"


@pytest.mark.asyncio
async def test_questdb_drop_unknown_table_returns_404():
    with patch(
        "api.routes.storage._questdb_list_tables",
        new=AsyncMock(return_value=["equity_snapshots"]),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/v1/storage/questdb/tables/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_questdb_unreachable_returns_503():
    with patch(
        "api.routes.storage._questdb_list_tables",
        new=AsyncMock(side_effect=Exception("connection refused")),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/storage/questdb/tables")
    assert resp.status_code == 503
