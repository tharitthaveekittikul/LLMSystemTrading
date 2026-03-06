from unittest.mock import AsyncMock, patch

import pytest

from ai.orchestrator import LLMRoleResult, analyze_market


def _mock_role_result(content: dict) -> LLMRoleResult:
    """Build a minimal LLMRoleResult for patching."""
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


def _market_analysis_content() -> dict:
    return {
        "trend": "bullish",
        "trend_strength": 0.75,
        "key_support": 1.080,
        "key_resistance": 1.090,
        "volatility": "medium",
        "context_notes": "Strong uptrend with volume confirmation.",
    }


def _execution_content() -> dict:
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

    ma_result = _mock_role_result(_market_analysis_content())
    ed_result = _mock_role_result(_execution_content())

    with (
        patch("ai.orchestrator._build_llm"),
        patch("ai.orchestrator._run_market_analysis", new=AsyncMock(return_value=ma_result)),
        patch("ai.orchestrator._run_execution_decision", new=AsyncMock(return_value=ed_result)),
        patch("ai.orchestrator.settings") as mock_cfg,
    ):
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
    assert result.signal.action in {"BUY", "SELL", "HOLD"}


@pytest.mark.asyncio
async def test_analyze_market_works_without_optional_args():
    """analyze_market still works with only required arguments (backward compat)."""
    ma_result = _mock_role_result(_market_analysis_content())
    ed_result = _mock_role_result(_execution_content())

    with (
        patch("ai.orchestrator._build_llm"),
        patch("ai.orchestrator._run_market_analysis", new=AsyncMock(return_value=ma_result)),
        patch("ai.orchestrator._run_execution_decision", new=AsyncMock(return_value=ed_result)),
        patch("ai.orchestrator.settings") as mock_cfg,
    ):
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
    assert result.signal.action in {"BUY", "SELL", "HOLD"}


@pytest.mark.asyncio
async def test_analyze_market_confidence_gate_downgrades_to_hold():
    """Signal below confidence threshold is downgraded to HOLD."""
    ma_result = _mock_role_result(_market_analysis_content())
    low_conf_content = {
        "action": "BUY",
        "entry": 1.085,
        "stop_loss": 1.080,
        "take_profit": 1.095,
        "confidence": 0.40,  # below threshold of 0.70
        "rationale": "Weak signal",
        "timeframe": "M15",
    }
    ed_result = _mock_role_result(low_conf_content)

    with (
        patch("ai.orchestrator._build_llm"),
        patch("ai.orchestrator._run_market_analysis", new=AsyncMock(return_value=ma_result)),
        patch("ai.orchestrator._run_execution_decision", new=AsyncMock(return_value=ed_result)),
        patch("ai.orchestrator.settings") as mock_cfg,
    ):
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
    assert result.signal.action == "HOLD"
