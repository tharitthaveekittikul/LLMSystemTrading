import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai.orchestrator import TradingSignal, analyze_market


def _mock_signal_dict() -> dict:
    return {
        "action": "BUY",
        "entry": 1.085,
        "stop_loss": 1.080,
        "take_profit": 1.095,
        "confidence": 0.85,
        "rationale": "Strong uptrend",
        "timeframe": "M15",
    }


@pytest.mark.asyncio
async def test_analyze_market_accepts_position_and_signal_args():
    """analyze_market accepts open_positions, recent_signals, news_context without error."""
    open_positions = [{"symbol": "EURUSD", "direction": "BUY", "volume": 0.1, "profit": 50.0}]
    recent_signals = [{"symbol": "EURUSD", "signal": "BUY", "confidence": 0.9, "rationale": "prior reason"}]

    with patch("ai.orchestrator._build_llm"):
        with patch("ai.orchestrator._PROMPT") as mock_prompt:
            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(return_value=_mock_signal_dict())
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            mock_chain.__or__ = MagicMock(return_value=mock_chain)

            with patch("ai.orchestrator.settings") as mock_cfg:
                mock_cfg.llm_provider = "openai"
                mock_cfg.llm_confidence_threshold = 0.70
                mock_cfg.openai_api_key = "test"

                result = await analyze_market(
                    symbol="EURUSD",
                    timeframe="M15",
                    current_price=1.085,
                    indicators={},
                    ohlcv=[],
                    open_positions=open_positions,
                    recent_signals=recent_signals,
                    news_context="Upcoming: EUR CPI at 14:00",
                )
    assert result.action in {"BUY", "SELL", "HOLD"}


@pytest.mark.asyncio
async def test_analyze_market_works_without_optional_args():
    """analyze_market still works with only required arguments (backward compat)."""
    with patch("ai.orchestrator._build_llm"):
        with patch("ai.orchestrator._PROMPT") as mock_prompt:
            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(return_value=_mock_signal_dict())
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            mock_chain.__or__ = MagicMock(return_value=mock_chain)

            with patch("ai.orchestrator.settings") as mock_cfg:
                mock_cfg.llm_provider = "openai"
                mock_cfg.llm_confidence_threshold = 0.70
                mock_cfg.openai_api_key = "test"

                result = await analyze_market(
                    symbol="EURUSD",
                    timeframe="M15",
                    current_price=1.085,
                    indicators={},
                    ohlcv=[],
                )
    assert result.action in {"BUY", "SELL", "HOLD"}
