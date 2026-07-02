"""Tests for live tick broadcasting to watched chart symbols.

A chart page subscribes to a symbol over the dashboard WebSocket via
{"action": "watch_symbol", "symbol": "..."}. ws.get_watched_symbols() tracks
this per-connection state; mt5_poller._fetch_and_broadcast polls that set
each cycle and pushes a "tick_update" event for every watched symbol.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_fetch_and_broadcast_pushes_tick_for_watched_symbols():
    from services.mt5_poller import AccountPollState, _fetch_and_broadcast

    bridge = AsyncMock()
    bridge.get_account_info.return_value = None
    bridge.get_positions.return_value = []
    bridge.get_orders.return_value = []
    bridge.get_tick.return_value = {"bid": 1900.5, "ask": 1900.8, "time": 1234567890}

    state = AccountPollState(account_id=1)

    with (
        patch("api.routes.ws.broadcast", new=AsyncMock()) as mock_broadcast,
        patch("api.routes.ws.get_watched_symbols", return_value={"XAUUSD.s"}),
    ):
        await _fetch_and_broadcast(1, bridge, state)

    bridge.get_tick.assert_any_await("XAUUSD.s")
    tick_calls = [c for c in mock_broadcast.await_args_list if c.args[1] == "tick_update"]
    assert len(tick_calls) == 1
    assert tick_calls[0].args[2] == {
        "symbol": "XAUUSD.s", "bid": 1900.5, "ask": 1900.8, "time": 1234567890,
    }


async def test_fetch_and_broadcast_skips_tick_when_nothing_watched():
    from services.mt5_poller import AccountPollState, _fetch_and_broadcast

    bridge = AsyncMock()
    bridge.get_account_info.return_value = None
    bridge.get_positions.return_value = []
    bridge.get_orders.return_value = []

    state = AccountPollState(account_id=1)

    with (
        patch("api.routes.ws.broadcast", new=AsyncMock()) as mock_broadcast,
        patch("api.routes.ws.get_watched_symbols", return_value=set()),
    ):
        await _fetch_and_broadcast(1, bridge, state)

    bridge.get_tick.assert_not_awaited()
    tick_calls = [c for c in mock_broadcast.await_args_list if c.args[1] == "tick_update"]
    assert len(tick_calls) == 0


def test_get_watched_symbols_reflects_registered_connections():
    from api.routes.ws import _watched_symbols, get_watched_symbols

    ws_a, ws_b = MagicMock(), MagicMock()
    _watched_symbols[42] = {ws_a: "EURUSD.s", ws_b: "XAUUSD.s"}
    try:
        assert get_watched_symbols(42) == {"EURUSD.s", "XAUUSD.s"}
        assert get_watched_symbols(999) == set()
    finally:
        _watched_symbols.pop(42, None)
