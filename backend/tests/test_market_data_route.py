"""Tests for GET /api/v1/market-data/{symbol}/{timeframe}.

Covers the broker-symbol resolution bugfix: the route must resolve a bare
symbol (e.g. "XAUUSD") to the broker's actual suffixed name (e.g. "XAUUSD.s")
via MT5Bridge.get_broker_symbol before fetching rates/tick — mirroring the
resolution already used by the strategy pipeline (_market_data.py,
abstract_runner.py). Without this, brokers that suffix symbol names return
no data and the chart route hangs/errors.
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def account(client):
    unique_login = int(datetime.now(UTC).strftime("%H%M%S%f")) % 2_000_000_000
    resp = await client.post("/api/v1/accounts", json={
        "name": "Market Data Test",
        "broker": "TestBroker",
        "login": unique_login,
        "password": "pass",
        "server": "test.server.com",
    })
    if resp.status_code != 201:
        pytest.skip("DB not available")
    account_id = resp.json()["id"]
    yield account_id
    await client.delete(f"/api/v1/accounts/{account_id}")


def _fake_candle():
    return {
        "time": datetime.now(UTC), "open": 1.0, "high": 1.1, "low": 0.9,
        "close": 1.05, "tick_volume": 100,
    }


async def test_get_ohlcv_resolves_broker_symbol(client, account):
    """A bare symbol like XAUUSD must be resolved to the broker's real name
    (e.g. XAUUSD.s) before get_rates/get_tick are called, and the resolved
    name is echoed back in the response so the frontend can align overlays."""
    with patch("api.routes.market_data.MT5Bridge") as mock_bridge_cls:
        mock_bridge = AsyncMock()
        mock_bridge.get_broker_symbol.return_value = "XAUUSD.s"
        mock_bridge.get_rates.return_value = [_fake_candle()]
        mock_bridge.get_tick.return_value = {"bid": 1.0, "ask": 1.0, "time": int(datetime.now(UTC).timestamp())}
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        resp = await client.get(
            f"/api/v1/market-data/XAUUSD/H1?account_id={account}&count=50"
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "XAUUSD.s"
    assert len(body["candles"]) == 1

    mock_bridge.get_broker_symbol.assert_awaited_once_with("XAUUSD")
    mock_bridge.get_rates.assert_awaited_once()
    assert mock_bridge.get_rates.await_args.args[0] == "XAUUSD.s"
    mock_bridge.get_tick.assert_awaited_once_with("XAUUSD.s")


async def test_get_ohlcv_unknown_timeframe_returns_400(client, account):
    resp = await client.get(
        f"/api/v1/market-data/XAUUSD/M3?account_id={account}&count=50"
    )
    assert resp.status_code == 400


async def test_get_ohlcv_missing_account_returns_404(client):
    resp = await client.get(
        "/api/v1/market-data/XAUUSD/H1?account_id=999999999&count=50"
    )
    assert resp.status_code == 404


async def test_get_ohlcv_mt5_failure_returns_503(client, account):
    with patch("api.routes.market_data.MT5Bridge") as mock_bridge_cls:
        mock_bridge_cls.return_value.__aenter__.side_effect = RuntimeError("MetaTrader5 package is not installed")
        resp = await client.get(
            f"/api/v1/market-data/XAUUSD/H1?account_id={account}&count=50"
        )
    assert resp.status_code == 503
