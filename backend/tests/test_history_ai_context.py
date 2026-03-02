"""Tests for trade history AI context wiring."""
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_analyze_market_accepts_trade_history_context():
    from ai.orchestrator import analyze_market
    sig = inspect.signature(analyze_market)
    assert "trade_history_context" in sig.parameters
    param = sig.parameters["trade_history_context"]
    assert param.default is None


def test_analyze_and_trade_has_expected_params():
    """analyze_and_trade signature must not break existing params."""
    import inspect
    from services.ai_trading import AITradingService
    sig = inspect.signature(AITradingService.analyze_and_trade)
    assert "account_id" in sig.parameters
    assert "symbol" in sig.parameters
    assert "timeframe" in sig.parameters
    assert "db" in sig.parameters


@pytest.mark.asyncio
async def test_analyze_market_injects_history_in_prompt():
    """When trade_history_context is provided, it appears in the LLM input."""
    from ai.orchestrator import analyze_market
    captured_inputs = {}

    async def mock_chain_invoke(inputs):
        captured_inputs.update(inputs)
        return {
            "action": "HOLD", "entry": 1.0, "stop_loss": 0.99,
            "take_profit": 1.01, "confidence": 0.5, "rationale": "test", "timeframe": "M15",
        }

    with patch("ai.orchestrator._DEFAULT_CHAIN") as mock_chain:
        mock_chain.ainvoke = mock_chain_invoke
        await analyze_market(
            symbol="EURUSD", timeframe="M15", current_price=1.085,
            indicators={}, ohlcv=[],
            trade_history_context="Recent closed trades (last 10):\n  - EURUSD BUY profit=+30.0",
        )

    assert "history_section" in captured_inputs
    assert "EURUSD BUY" in captured_inputs["history_section"]


@pytest.mark.asyncio
async def test_analyze_market_empty_history_section_when_none():
    from ai.orchestrator import analyze_market
    captured_inputs = {}

    async def mock_chain_invoke(inputs):
        captured_inputs.update(inputs)
        return {
            "action": "HOLD", "entry": 1.0, "stop_loss": 0.99,
            "take_profit": 1.01, "confidence": 0.5, "rationale": "test", "timeframe": "M15",
        }

    with patch("ai.orchestrator._DEFAULT_CHAIN") as mock_chain:
        mock_chain.ainvoke = mock_chain_invoke
        await analyze_market(
            symbol="EURUSD", timeframe="M15", current_price=1.085,
            indicators={}, ohlcv=[],
        )

    assert captured_inputs["history_section"] == ""


@pytest.mark.asyncio
async def test_analyze_and_trade_calls_get_raw_deals():
    """analyze_and_trade must call HistoryService.get_raw_deals for LLM context."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from ai.orchestrator import LLMAnalysisResult, TradingSignal

    def _make_signal():
        return TradingSignal(
            action="HOLD", entry=1.085, stop_loss=1.080,
            take_profit=1.090, confidence=0.5,
            rationale="test", timeframe="M15",
        )

    def _make_llm_result():
        return LLMAnalysisResult(signal=_make_signal(), prompt_text="", raw_response={})

    mock_db = AsyncMock()
    mock_account = MagicMock(
        id=1, login=12345, password_encrypted="enc", server="srv",
        mt5_path="", max_lot_size=0.1, is_active=True,
        auto_trade_enabled=True, paper_trade_enabled=False,
    )
    mock_db.get.return_value = mock_account
    # db.execute is AsyncMock; await db.execute(...) returns its return_value.
    # Use plain MagicMock so sync calls on the result work correctly.
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none.return_value = None
    _exec_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = _exec_result

    mock_hist_svc = MagicMock()
    mock_hist_svc.get_raw_deals = AsyncMock(return_value=[])

    with (
        patch("services.ai_trading.check_llm_rate_limit", return_value=True),
        patch("services.ai_trading.get_candle_cache", return_value=None),
        patch("services.ai_trading.set_candle_cache"),
        patch("services.ai_trading.MT5Bridge") as mock_bridge_cls,
        # analyze_market is async and returns LLMAnalysisResult
        patch("services.ai_trading.analyze_market", new=AsyncMock(return_value=_make_llm_result())),
        patch("services.ai_trading.broadcast"),
        patch("services.ai_trading.decrypt", return_value="password"),
        patch("services.ai_trading.HistoryService", return_value=mock_hist_svc),
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

    mock_hist_svc.get_raw_deals.assert_called_once_with(mock_account, days=30)
    assert result.signal.action == "HOLD"
