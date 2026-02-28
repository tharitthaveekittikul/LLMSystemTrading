"""Tests for MT5Bridge history methods."""
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from mt5.bridge import AccountCredentials, MT5Bridge


def _make_creds() -> AccountCredentials:
    return AccountCredentials(login=12345, password="pw", server="srv")


def _make_deal(ticket: int, position_id: int, entry: int, deal_type: int,
               symbol: str = "EURUSD", volume: float = 0.1,
               price: float = 1.0850, profit: float = 0.0,
               ts: int = 1700000000) -> MagicMock:
    d = MagicMock()
    d._asdict.return_value = {
        "ticket": ticket, "position_id": position_id, "entry": entry,
        "type": deal_type, "symbol": symbol, "volume": volume,
        "price": price, "profit": profit, "commission": 0.0,
        "swap": 0.0, "time": ts,
    }
    return d


def test_bridge_has_history_deals_get():
    assert hasattr(MT5Bridge, "history_deals_get")


def test_bridge_has_history_orders_get():
    assert hasattr(MT5Bridge, "history_orders_get")


def test_history_deals_get_is_coroutine():
    assert asyncio.iscoroutinefunction(MT5Bridge.history_deals_get)


def test_history_orders_get_is_coroutine():
    assert asyncio.iscoroutinefunction(MT5Bridge.history_orders_get)


@pytest.mark.asyncio
async def test_history_deals_get_returns_dicts():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=90)
    date_to = datetime.now(UTC)
    deal = _make_deal(101, 200, 1, 1, profit=30.0)

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.history_deals_get.return_value = [deal]
        result = await bridge.history_deals_get(date_from, date_to)

    assert len(result) == 1
    assert result[0]["ticket"] == 101
    assert result[0]["profit"] == 30.0


@pytest.mark.asyncio
async def test_history_deals_get_returns_empty_on_none():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=90)
    date_to = datetime.now(UTC)

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.history_deals_get.return_value = None
        result = await bridge.history_deals_get(date_from, date_to)

    assert result == []


@pytest.mark.asyncio
async def test_history_orders_get_returns_dicts():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=90)
    date_to = datetime.now(UTC)
    order = _make_deal(999, 300, 0, 0, symbol="GBPUSD")

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.history_orders_get.return_value = [order]
        result = await bridge.history_orders_get(date_from, date_to)

    assert len(result) == 1
    assert result[0]["ticket"] == 999
    assert result[0]["symbol"] == "GBPUSD"


@pytest.mark.asyncio
async def test_history_deals_raises_when_mt5_unavailable():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=1)
    date_to = datetime.now(UTC)

    with patch("mt5.bridge.MT5_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="MetaTrader5 package is not installed"):
            await bridge.history_deals_get(date_from, date_to)


@pytest.mark.asyncio
async def test_history_orders_get_returns_empty_on_none():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=90)
    date_to = datetime.now(UTC)

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.history_orders_get.return_value = None
        result = await bridge.history_orders_get(date_from, date_to)

    assert result == []


@pytest.mark.asyncio
async def test_history_orders_raises_when_mt5_unavailable():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=1)
    date_to = datetime.now(UTC)

    with patch("mt5.bridge.MT5_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="MetaTrader5 package is not installed"):
            await bridge.history_orders_get(date_from, date_to)
