"""Tests for executor pending order support."""
import pytest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError


def test_order_request_accepts_pending_actions():
    from mt5.executor import OrderRequest
    for action in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
        req = OrderRequest(
            symbol="XAUUSD", action=action, volume=0.1,
            entry_price=1900.0, stop_loss=1890.0, take_profit=1920.0,
        )
        assert req.action == action


def test_order_request_rejects_hold():
    from mt5.executor import OrderRequest
    with pytest.raises(ValidationError):
        OrderRequest(
            symbol="XAUUSD", action="HOLD", volume=0.1,
            entry_price=1900.0, stop_loss=1890.0, take_profit=1920.0,
        )


def test_order_request_rejects_unknown():
    from mt5.executor import OrderRequest
    with pytest.raises(ValidationError):
        OrderRequest(
            symbol="XAUUSD", action="LONG", volume=0.1,
            entry_price=1900.0, stop_loss=1890.0, take_profit=1920.0,
        )


@pytest.mark.asyncio
async def test_place_order_uses_pending_action_for_buy_limit():
    """BUY_LIMIT sends TRADE_ACTION_PENDING (5) to MT5, not TRADE_ACTION_DEAL (1)."""
    from mt5.executor import MT5Executor, OrderRequest

    mock_bridge = AsyncMock()
    mock_bridge.get_positions = AsyncMock(return_value=[])
    mock_bridge.is_autotrading_enabled = AsyncMock(return_value=True)
    mock_bridge.get_filling_mode = AsyncMock(return_value=1)
    mock_bridge.send_order = AsyncMock(return_value={"retcode": 10009, "order": 12345})

    with (
        patch("mt5.executor.kill_switch_active", return_value=False),
        patch("mt5.executor.exceeds_position_limit", return_value=(False, "")),
    ):
        executor = MT5Executor(mock_bridge)
        req = OrderRequest(
            symbol="XAUUSD", action="BUY_LIMIT", volume=0.1,
            entry_price=1900.0, stop_loss=1890.0, take_profit=1920.0,
        )
        result = await executor.place_order(req)

    assert result.success is True
    sent_request = mock_bridge.send_order.call_args[0][0]
    assert sent_request["action"] == 5   # TRADE_ACTION_PENDING
    assert sent_request["type"] == 2     # ORDER_TYPE_BUY_LIMIT
    assert "deviation" not in sent_request


@pytest.mark.asyncio
async def test_place_order_uses_deal_action_for_buy():
    """BUY sends TRADE_ACTION_DEAL (1) with deviation."""
    from mt5.executor import MT5Executor, OrderRequest

    mock_bridge = AsyncMock()
    mock_bridge.get_positions = AsyncMock(return_value=[])
    mock_bridge.is_autotrading_enabled = AsyncMock(return_value=True)
    mock_bridge.get_filling_mode = AsyncMock(return_value=1)
    mock_bridge.send_order = AsyncMock(return_value={"retcode": 10009, "order": 12346})

    with (
        patch("mt5.executor.kill_switch_active", return_value=False),
        patch("mt5.executor.exceeds_position_limit", return_value=(False, "")),
    ):
        executor = MT5Executor(mock_bridge)
        req = OrderRequest(
            symbol="XAUUSD", action="BUY", volume=0.1,
            entry_price=1905.0, stop_loss=1890.0, take_profit=1925.0,
        )
        result = await executor.place_order(req)

    assert result.success is True
    sent_request = mock_bridge.send_order.call_args[0][0]
    assert sent_request["action"] == 1   # TRADE_ACTION_DEAL
    assert sent_request["type"] == 0     # ORDER_TYPE_BUY
    assert "deviation" in sent_request
