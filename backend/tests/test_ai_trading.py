import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai.orchestrator import TradingSignal


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


@pytest.mark.asyncio
async def test_analyze_hold_signal_no_order():
    """HOLD signal must not place an order."""
    mock_db = AsyncMock()
    mock_db.get.return_value = MagicMock(
        id=1, login=12345, password_encrypted="enc", server="srv",
        max_lot_size=0.1, is_active=True,
    )

    with (
        patch("services.ai_trading.check_llm_rate_limit", return_value=True),
        patch("services.ai_trading.get_candle_cache", return_value=None),
        patch("services.ai_trading.set_candle_cache"),
        patch("services.ai_trading.MT5Bridge") as mock_bridge_cls,
        patch("services.ai_trading.analyze_market", return_value=_make_signal("HOLD")),
        patch("services.ai_trading.broadcast"),
        patch("services.ai_trading.decrypt", return_value="password"),
    ):
        mock_bridge = AsyncMock()
        mock_bridge.get_rates.return_value = [
            {"time": "t", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 100}
        ] * 20
        mock_bridge.get_tick.return_value = {"bid": 1.085, "ask": 1.086}
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

    mock_db = AsyncMock()
    mock_db.get.return_value = MagicMock(id=1, is_active=True)

    with patch("services.ai_trading.check_llm_rate_limit", return_value=False):
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
