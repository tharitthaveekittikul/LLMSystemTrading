from unittest.mock import AsyncMock, patch

import pytest

from mt5.executor import MT5Executor, OrderRequest
from services.risk_manager import exceeds_drawdown_limit, exceeds_position_limit


def test_position_limit_not_exceeded():
    positions = [{"ticket": 1}, {"ticket": 2}]
    exceeded, reason = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is False
    assert reason == ""


def test_position_limit_exactly_at_max():
    positions = [{"ticket": i} for i in range(5)]
    exceeded, reason = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is True
    assert "5/5" in reason


def test_position_limit_exceeded():
    positions = [{"ticket": i} for i in range(6)]
    exceeded, _ = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is True


def test_drawdown_not_exceeded():
    exceeded, reason = exceeds_drawdown_limit(equity=9500.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is False
    assert reason == ""


def test_drawdown_exactly_at_limit():
    # 10000 - 9000 = 1000 loss = 10% drawdown
    exceeded, reason = exceeds_drawdown_limit(equity=9000.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is True
    assert "10.00%" in reason


def test_drawdown_exceeded():
    exceeded, _ = exceeds_drawdown_limit(equity=8000.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is True


def test_drawdown_zero_balance_safe():
    # Guard against division by zero
    exceeded, _ = exceeds_drawdown_limit(equity=0.0, balance=0.0, max_drawdown_pct=10.0)
    assert exceeded is False


def _make_order() -> OrderRequest:
    return OrderRequest(
        symbol="EURUSD",
        direction="BUY",
        volume=0.1,
        entry_price=1.0850,
        stop_loss=1.0800,
        take_profit=1.0950,
    )


@pytest.mark.asyncio
async def test_executor_rejects_when_position_limit_hit():
    """place_order must return failure when max open positions is reached."""
    mock_bridge = AsyncMock()
    # Simulate 5 open positions (at the limit)
    mock_bridge.get_positions.return_value = [{"ticket": i} for i in range(5)]

    executor = MT5Executor(bridge=mock_bridge)

    with patch("mt5.executor.kill_switch_active", return_value=False):
        with patch("mt5.executor.settings") as mock_settings:
            mock_settings.max_open_positions = 5
            result = await executor.place_order(_make_order())

    assert result.success is False
    assert "Position limit" in result.error
    mock_bridge.send_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_dry_run_does_not_call_bridge():
    """dry_run=True must succeed without calling bridge.send_order."""
    mock_bridge = AsyncMock()
    mock_bridge.get_positions.return_value = []

    executor = MT5Executor(bridge=mock_bridge)
    with patch("mt5.executor.kill_switch_active", return_value=False):
        with patch("mt5.executor.settings") as mock_settings:
            mock_settings.max_open_positions = 10
            result = await executor.place_order(_make_order(), dry_run=True)

    assert result.success is True
    assert result.ticket is not None
    assert result.ticket < 0  # simulated ticket is negative
    mock_bridge.send_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_dry_run_close_does_not_call_bridge():
    """dry_run=True on close_position must succeed without MT5 call."""
    mock_bridge = AsyncMock()

    executor = MT5Executor(bridge=mock_bridge)
    with patch("mt5.executor.kill_switch_active", return_value=False):
        result = await executor.close_position(ticket=12345, symbol="EURUSD", volume=0.1, dry_run=True)

    assert result.success is True
    mock_bridge.send_order.assert_not_called()
