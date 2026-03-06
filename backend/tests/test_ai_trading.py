import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai.orchestrator import LLMAnalysisResult, LLMRoleResult, TradingSignal


def _make_signal(action: str, confidence: float = 0.85) -> TradingSignal:
    return TradingSignal(
        action=action,
        entry=1.0850,
        stop_loss=1.0800,
        take_profit=1.0950,
        confidence=confidence,
        rationale="Test signal",
        timeframe="M15",
    )


def _make_role_result() -> LLMRoleResult:
    return LLMRoleResult(
        content="analysis",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        model="gemini-2.5-flash",
        provider="google",
        duration_ms=500,
        raw_text="analysis",
    )


def _make_llm_result(action: str, confidence: float = 0.85) -> LLMAnalysisResult:
    signal = _make_signal(action, confidence)
    role = _make_role_result()
    return LLMAnalysisResult(
        signal=signal,
        market_analysis=role,
        chart_vision=None,
        execution_decision=role,
    )


@pytest.mark.asyncio
async def test_analyze_hold_signal_no_order():
    """HOLD signal must not place an order."""
    mock_db = AsyncMock()
    mock_db.get.return_value = MagicMock(
        id=1, login=12345, password_encrypted="enc", server="srv",
        max_lot_size=0.1, is_active=True,
    )
    # db.execute is AsyncMock; await db.execute(...) returns its return_value.
    # Set return_value to a plain MagicMock so that sync method calls like
    # .scalar_one_or_none() and .scalars().all() work correctly (not as coroutines).
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none.return_value = None
    _exec_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = _exec_result

    with (
        patch("services.ai_trading.check_llm_rate_limit", return_value=True),
        patch("services.ai_trading.get_candle_cache", return_value=None),
        patch("services.ai_trading.set_candle_cache"),
        patch("services.ai_trading.MT5Bridge") as mock_bridge_cls,
        # analyze_market is async and returns LLMAnalysisResult
        patch("services.ai_trading.analyze_market", new=AsyncMock(return_value=_make_llm_result("HOLD"))),
        patch("services.ai_trading.broadcast"),
        patch("services.ai_trading.decrypt", return_value="password"),
    ):
        mock_bridge = AsyncMock()
        mock_bridge.get_rates.return_value = [
            {"time": "t", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 100}
        ] * 50
        mock_bridge.get_tick.return_value = {"bid": 1.085, "ask": 1.086}
        mock_bridge.get_positions.return_value = []
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        from services.ai_trading import AITradingService
        service = AITradingService()
        result = await service.analyze_and_trade(
            account_id=1, symbol="EURUSD", timeframe="M15", db=mock_db
        )

    assert result.signal.action == "HOLD"
    assert result.order_placed is False
    assert result.ticket is None


@pytest.mark.asyncio
async def test_analyze_rate_limited_raises():
    """Rate-limited request raises HTTP 429."""
    from fastapi import HTTPException

    _candles = [
        {"time": "t", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 100}
    ] * 50

    mock_db = AsyncMock()
    mock_db.get.return_value = MagicMock(id=1, is_active=True)
    # db.execute is AsyncMock; await db.execute(...) returns its return_value.
    # Use plain MagicMock so sync calls on the result work correctly.
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none.return_value = None
    _exec_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = _exec_result

    with (
        patch("services.ai_trading.check_llm_rate_limit", return_value=False),
        # Return a cache hit so the MT5Bridge path is skipped
        patch("services.ai_trading.get_candle_cache", return_value=_candles),
        patch("services.ai_trading.decrypt", return_value="password"),
        patch("services.ai_trading.MT5Bridge") as mock_bridge_cls,
        patch("services.ai_trading.broadcast"),
    ):
        mock_bridge = AsyncMock()
        mock_bridge.get_positions.return_value = []
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        from services.ai_trading import AITradingService
        service = AITradingService()
        with pytest.raises(HTTPException) as exc_info:
            await service.analyze_and_trade(
                account_id=1, symbol="EURUSD", timeframe="M15", db=mock_db
            )
    assert exc_info.value.status_code == 429


def test_strategy_overrides_defaults():
    from services.ai_trading import StrategyOverrides
    o = StrategyOverrides()
    assert o.lot_size is None
    assert o.sl_pips is None
    assert o.tp_pips is None
    assert o.news_filter is True
    assert o.custom_prompt is None


def test_analyze_and_trade_has_strategy_params():
    import inspect
    from services.ai_trading import AITradingService
    sig = inspect.signature(AITradingService.analyze_and_trade)
    assert "strategy_id" in sig.parameters
    assert "strategy_overrides" in sig.parameters


def test_orchestrator_accepts_system_prompt_override():
    import inspect
    from ai.orchestrator import analyze_market
    sig = inspect.signature(analyze_market)
    assert "system_prompt_override" in sig.parameters


# ── _calculate_lot_size unit tests ──────────────────────────────────────────

def test_calculate_lot_size_normal():
    """Standard EURUSD example: $10k account, 1% risk, 50-pip SL, $10 pip value → 0.20 lots."""
    from services.ai_trading import _calculate_lot_size
    result = _calculate_lot_size(
        balance=10_000.0,
        risk_pct=0.01,
        sl_pips=50.0,
        pip_value_per_lot=10.0,
        max_lot=1.0,
    )
    assert result == 0.20


def test_calculate_lot_size_clamps_to_min():
    """Very small balance should still return minimum 0.01."""
    from services.ai_trading import _calculate_lot_size
    result = _calculate_lot_size(
        balance=10.0,
        risk_pct=0.01,
        sl_pips=50.0,
        pip_value_per_lot=10.0,
        max_lot=1.0,
    )
    assert result == 0.01


def test_calculate_lot_size_clamps_to_max():
    """Very large calculated size must not exceed max_lot."""
    from services.ai_trading import _calculate_lot_size
    result = _calculate_lot_size(
        balance=1_000_000.0,
        risk_pct=0.05,
        sl_pips=5.0,
        pip_value_per_lot=10.0,
        max_lot=0.5,
    )
    assert result == 0.5


def test_calculate_lot_size_zero_sl_returns_min():
    """sl_pips=0 must safely return min_lot instead of division-by-zero."""
    from services.ai_trading import _calculate_lot_size
    result = _calculate_lot_size(
        balance=10_000.0,
        risk_pct=0.01,
        sl_pips=0.0,
        pip_value_per_lot=10.0,
        max_lot=1.0,
    )
    assert result == 0.01
