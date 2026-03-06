"""Tests for trade history AI context wiring."""
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai.orchestrator import LLMAnalysisResult, LLMRoleResult, TradingSignal


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_role_result(content: dict | str = "ok") -> LLMRoleResult:
    return LLMRoleResult(
        content=content,
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        model="gpt-4o",
        provider="openai",
        duration_ms=300,
        raw_text=str(content),
    )


def _make_signal() -> TradingSignal:
    return TradingSignal(
        action="HOLD", entry=1.085, stop_loss=1.080,
        take_profit=1.090, confidence=0.5,
        rationale="test", timeframe="M15",
    )


def _make_llm_result() -> LLMAnalysisResult:
    role = _make_role_result()
    return LLMAnalysisResult(
        signal=_make_signal(),
        market_analysis=role,
        chart_vision=None,
        execution_decision=role,
    )


# ── Signature tests (no mocking needed) ──────────────────────────────────────

def test_analyze_market_accepts_trade_history_context():
    from ai.orchestrator import analyze_market
    sig = inspect.signature(analyze_market)
    assert "trade_history_context" in sig.parameters
    param = sig.parameters["trade_history_context"]
    assert param.default is None


def test_analyze_and_trade_has_expected_params():
    """analyze_and_trade signature must not break existing params."""
    from services.ai_trading import AITradingService
    sig = inspect.signature(AITradingService.analyze_and_trade)
    assert "account_id" in sig.parameters
    assert "symbol" in sig.parameters
    assert "timeframe" in sig.parameters
    assert "db" in sig.parameters


# ── trade_history_context wiring tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_market_injects_history_in_prompt():
    """When trade_history_context is provided, _run_market_analysis receives it."""
    from ai.orchestrator import analyze_market

    captured: dict = {}

    async def mock_run_market_analysis(_llm, _symbol, _timeframe, _current_price,
                                       _indicators, _ohlcv, _open_positions,
                                       _recent_signals, _news_context,
                                       trade_history_context, _regime_context):
        captured["trade_history_context"] = trade_history_context
        return _make_role_result({
            "trend": "bullish", "trend_strength": 0.7,
            "key_support": 1.08, "key_resistance": 1.09,
            "volatility": "medium", "context_notes": "test",
        })

    ed_result = _make_role_result({
        "action": "HOLD", "entry": 1.0, "stop_loss": 0.99,
        "take_profit": 1.01, "confidence": 0.5,
        "rationale": "test", "timeframe": "M15",
    })

    history_text = "Recent closed trades (last 10):\n  - EURUSD BUY profit=+30.0"

    with (
        patch("ai.orchestrator._build_llm"),
        patch("ai.orchestrator._run_market_analysis", side_effect=mock_run_market_analysis),
        patch("ai.orchestrator._run_execution_decision", new=AsyncMock(return_value=ed_result)),
        patch("ai.orchestrator.settings") as mock_cfg,
    ):
        mock_cfg.llm_provider = "openai"
        mock_cfg.llm_confidence_threshold = 0.70
        mock_cfg.openai_api_key = "test"

        await analyze_market(
            symbol="EURUSD", timeframe="M15", current_price=1.085,
            indicators={}, ohlcv=[],
            trade_history_context=history_text,
        )

    assert captured.get("trade_history_context") == history_text
    assert "EURUSD BUY" in captured["trade_history_context"]


@pytest.mark.asyncio
async def test_analyze_market_empty_history_section_when_none():
    """When trade_history_context=None, _run_market_analysis receives None."""
    from ai.orchestrator import analyze_market

    captured: dict = {}

    async def mock_run_market_analysis(_llm, _symbol, _timeframe, _current_price,
                                       _indicators, _ohlcv, _open_positions,
                                       _recent_signals, _news_context,
                                       trade_history_context, _regime_context):
        captured["trade_history_context"] = trade_history_context
        return _make_role_result({
            "trend": "ranging", "trend_strength": 0.4,
            "key_support": 1.08, "key_resistance": 1.09,
            "volatility": "low", "context_notes": "test",
        })

    ed_result = _make_role_result({
        "action": "HOLD", "entry": 1.0, "stop_loss": 0.99,
        "take_profit": 1.01, "confidence": 0.5,
        "rationale": "test", "timeframe": "M15",
    })

    with (
        patch("ai.orchestrator._build_llm"),
        patch("ai.orchestrator._run_market_analysis", side_effect=mock_run_market_analysis),
        patch("ai.orchestrator._run_execution_decision", new=AsyncMock(return_value=ed_result)),
        patch("ai.orchestrator.settings") as mock_cfg,
    ):
        mock_cfg.llm_provider = "openai"
        mock_cfg.llm_confidence_threshold = 0.70
        mock_cfg.openai_api_key = "test"

        await analyze_market(
            symbol="EURUSD", timeframe="M15", current_price=1.085,
            indicators={}, ohlcv=[],
        )

    assert captured.get("trade_history_context") is None


@pytest.mark.asyncio
async def test_analyze_and_trade_calls_get_raw_deals():
    """analyze_and_trade must call HistoryService.get_raw_deals for LLM context."""
    mock_db = AsyncMock()
    mock_account = MagicMock(
        id=1, login=12345, password_encrypted="enc", server="srv",
        mt5_path="", max_lot_size=0.1, is_active=True,
        auto_trade_enabled=True, paper_trade_enabled=False,
    )
    mock_db.get.return_value = mock_account
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
