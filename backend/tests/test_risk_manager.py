"""Tests for risk_manager — all 4 rules."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.risk_manager import (
    RiskConfig,
    check_drawdown,
    check_hedging,
    check_position_limit,
    check_rate_limit,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _cfg(**kwargs) -> RiskConfig:
    """Build a RiskConfig with all rules enabled and sensible defaults."""
    defaults = dict(
        drawdown_check_enabled=True,
        max_drawdown_pct=10.0,
        position_limit_enabled=True,
        max_open_positions=5,
        rate_limit_enabled=True,
        rate_limit_max_trades=3,
        rate_limit_window_hours=4.0,
        hedging_allowed=False,
    )
    defaults.update(kwargs)
    return RiskConfig(**defaults)


def _pos(symbol: str = "EURUSD", pos_type: int = 0, ticket: int = 1) -> dict:
    """Build a fake MT5 position dict. type 0=BUY, 1=SELL."""
    return {"ticket": ticket, "symbol": symbol, "type": pos_type}


# ── check_drawdown ─────────────────────────────────────────────────────────

def test_drawdown_disabled_always_passes():
    cfg = _cfg(drawdown_check_enabled=False, max_drawdown_pct=0.1)
    exceeded, reason = check_drawdown(1.0, 10000.0, cfg)
    assert exceeded is False
    assert reason == ""


def test_drawdown_not_exceeded():
    exceeded, reason = check_drawdown(equity=9500.0, balance=10000.0, cfg=_cfg())
    assert exceeded is False


def test_drawdown_exactly_at_limit():
    exceeded, reason = check_drawdown(equity=9000.0, balance=10000.0, cfg=_cfg(max_drawdown_pct=10.0))
    assert exceeded is True
    assert "10.00%" in reason


def test_drawdown_zero_balance_safe():
    exceeded, _ = check_drawdown(equity=0.0, balance=0.0, cfg=_cfg())
    assert exceeded is False


# ── check_position_limit ───────────────────────────────────────────────────

def test_position_limit_disabled_always_passes():
    positions = [_pos() for _ in range(100)]
    exceeded, _ = check_position_limit(positions, _cfg(position_limit_enabled=False))
    assert exceeded is False


def test_position_limit_not_exceeded():
    positions = [_pos(ticket=i) for i in range(3)]
    exceeded, _ = check_position_limit(positions, _cfg(max_open_positions=5))
    assert exceeded is False


def test_position_limit_at_max():
    positions = [_pos(ticket=i) for i in range(5)]
    exceeded, reason = check_position_limit(positions, _cfg(max_open_positions=5))
    assert exceeded is True
    assert "5/5" in reason


# ── check_hedging ──────────────────────────────────────────────────────────

def test_hedging_allowed_always_passes():
    positions = [_pos("EURUSD", pos_type=1)]  # existing SELL
    exceeded, _ = check_hedging("EURUSD", "BUY", positions, _cfg(hedging_allowed=True))
    assert exceeded is False


def test_hedging_disabled_rejects_opposite_side():
    positions = [_pos("EURUSD", pos_type=1)]  # existing SELL
    exceeded, reason = check_hedging("EURUSD", "BUY", positions, _cfg(hedging_allowed=False))
    assert exceeded is True
    assert "EURUSD" in reason


def test_hedging_disabled_allows_same_side():
    positions = [_pos("EURUSD", pos_type=0)]  # existing BUY
    exceeded, _ = check_hedging("EURUSD", "BUY", positions, _cfg(hedging_allowed=False))
    assert exceeded is False


def test_hedging_disabled_different_symbol_passes():
    positions = [_pos("GBPUSD", pos_type=1)]  # SELL on different symbol
    exceeded, _ = check_hedging("EURUSD", "BUY", positions, _cfg(hedging_allowed=False))
    assert exceeded is False


def test_hedging_sell_blocked_by_existing_buy():
    positions = [_pos("EURUSD", pos_type=0)]  # existing BUY
    exceeded, reason = check_hedging("EURUSD", "SELL", positions, _cfg(hedging_allowed=False))
    assert exceeded is True


# ── check_rate_limit ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_disabled_always_passes():
    mock_db = AsyncMock()
    exceeded, _ = await check_rate_limit("EURUSD", _cfg(rate_limit_enabled=False), mock_db)
    assert exceeded is False
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_rate_limit_not_exceeded():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 2
    mock_db.execute.return_value = mock_result

    exceeded, _ = await check_rate_limit(
        "EURUSD", _cfg(rate_limit_max_trades=3, rate_limit_window_hours=4.0), mock_db
    )
    assert exceeded is False


@pytest.mark.asyncio
async def test_rate_limit_at_max():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 3
    mock_db.execute.return_value = mock_result

    exceeded, reason = await check_rate_limit(
        "EURUSD", _cfg(rate_limit_max_trades=3, rate_limit_window_hours=4.0), mock_db
    )
    assert exceeded is True
    assert "3/3" in reason
    assert "EURUSD" in reason


@pytest.mark.asyncio
async def test_rate_limit_queries_correct_symbol():
    """Verify DB is queried (symbol filtering is done in SQL)."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_db.execute.return_value = mock_result

    await check_rate_limit("XAUUSD", _cfg(), mock_db)
    mock_db.execute.assert_called_once()


# ── Executor integration tests ─────────────────────────────────────────────

from mt5.executor import MT5Executor, OrderRequest


def _make_order() -> OrderRequest:
    return OrderRequest(
        symbol="EURUSD",
        action="BUY",
        volume=0.1,
        entry_price=1.0850,
        stop_loss=1.0800,
        take_profit=1.0950,
    )


def _risk_cfg_all_off() -> RiskConfig:
    return RiskConfig(
        position_limit_enabled=False,
        rate_limit_enabled=False,
        hedging_allowed=True,
    )


@pytest.mark.asyncio
async def test_executor_rejects_when_position_limit_hit():
    mock_bridge = AsyncMock()
    mock_bridge.get_positions.return_value = [{"ticket": i} for i in range(5)]

    cfg = RiskConfig(position_limit_enabled=True, max_open_positions=5,
                     rate_limit_enabled=False, hedging_allowed=True)
    executor = MT5Executor(bridge=mock_bridge)

    with patch("mt5.executor.kill_switch_active", return_value=False), \
         patch("mt5.executor.load_risk_config", new=AsyncMock(return_value=cfg)), \
         patch("mt5.executor.AsyncSessionLocal") as mock_session_cls:
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await executor.place_order(_make_order())

    assert result.success is False
    assert "Position limit" in result.error
    mock_bridge.send_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_dry_run_skips_bridge():
    mock_bridge = AsyncMock()
    mock_bridge.get_positions.return_value = []

    executor = MT5Executor(bridge=mock_bridge)

    with patch("mt5.executor.kill_switch_active", return_value=False), \
         patch("mt5.executor.load_risk_config", new=AsyncMock(return_value=_risk_cfg_all_off())), \
         patch("mt5.executor.AsyncSessionLocal") as mock_session_cls:
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await executor.place_order(_make_order(), dry_run=True)

    assert result.success is True
    assert result.ticket < 0
    mock_bridge.send_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_dry_run_close_does_not_call_bridge():
    mock_bridge = AsyncMock()
    executor = MT5Executor(bridge=mock_bridge)
    with patch("mt5.executor.kill_switch_active", return_value=False):
        result = await executor.close_position(ticket=12345, symbol="EURUSD", volume=0.1, dry_run=True)
    assert result.success is True
    mock_bridge.send_order.assert_not_called()
