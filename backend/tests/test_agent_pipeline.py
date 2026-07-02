import json
import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai.agent_pipeline import (
    AgentPipelineState,
    _indicator_vote,
    _pattern_vote,
    _quorum_verdict,
    _trend_vote,
    build_pipeline,
)


def make_ohlcv(n=60):
    price = 1.1000
    candles = []
    for i in range(n):
        open_ = price
        high = open_ + random.uniform(0, 0.002)
        low = open_ - random.uniform(0, 0.002)
        close = random.uniform(low, high)
        candles.append(
            {
                "time": f"2024-01-{i+1:02d}",
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": random.randint(100, 1000),
            }
        )
        price = close
    return candles


def mock_llm(response_json: dict) -> MagicMock:
    """Return a MagicMock LLM whose ainvoke returns a message with JSON content."""
    llm = MagicMock()
    message = MagicMock()
    message.content = json.dumps(response_json)
    llm.ainvoke = AsyncMock(return_value=message)
    return llm


def _make_settings(
    enable_indicator_agent: bool = True,
    enable_pattern_agent: bool = True,
    enable_trend_agent: bool = True,
) -> MagicMock:
    settings = MagicMock()
    settings.enable_indicator_agent = enable_indicator_agent
    settings.enable_pattern_agent = enable_pattern_agent
    settings.enable_trend_agent = enable_trend_agent
    return settings


_MARKET_ANALYSIS_RESPONSE = {
    "trend": "bullish",
    "trend_strength": 0.7,
    "key_support": 1.09,
    "key_resistance": 1.12,
    "volatility": "medium",
    "context_notes": "test",
}

_INDICATOR_RESPONSE = {
    "overall": "bullish",
    "confidence": "high",
    "rsi": {"value": 55, "signal": "neutral", "trend": "up"},
    "macd": {"crossover": "bullish", "histogram_trend": "up", "signal": "buy"},
    "stoch": {"k": 60, "d": 55, "signal": "neutral"},
    "roc": {"value": 0.5, "signal": "bullish"},
    "willr": {"value": -30, "signal": "neutral"},
}

_DECISION_RESPONSE = {
    "signal": "LONG",
    "confidence": 0.8,
    "justification": "test",
    "forecast_horizon": "4h",
    "risk_reward_ratio": 1.5,
    "suggested_entry": 1.105,
    "invalidation_condition": "below 1.09",
}

_TREND_RESPONSE = {
    "trend_direction": "bullish",
    "trend_strength": 0.7,
    "support_levels": [1.09],
    "resistance_levels": [1.12],
    "notes": "test",
}

_PATTERN_RESPONSE = {
    "patterns_detected": [],
    "overall_bias": "bullish",
    "notes": "no pattern",
}


def _make_initial_state() -> AgentPipelineState:
    return AgentPipelineState(
        symbol="EURUSD",
        timeframe="H1",
        current_price=1.1050,
        ohlcv=make_ohlcv(60),
        indicators={
            "rsi": 55.0,
            "macd_line": 0.001,
            "macd_signal": 0.0005,
            "macd_histogram": 0.0005,
            "stoch_k": 60.0,
            "stoch_d": 55.0,
            "roc": 0.5,
            "willr": -30.0,
        },
        chart_image_b64=None,
        trendline_chart_b64=None,
        news_context=None,
        open_positions=None,
        trade_history=None,
        market_context=None,
        indicator_report=None,
        pattern_report=None,
        trend_report=None,
        final_signal=None,
        error=None,
    )


def test_build_pipeline_creates_compiled_graph():
    llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    settings = _make_settings(
        enable_indicator_agent=True,
        enable_pattern_agent=True,
        enable_trend_agent=True,
    )
    pipeline = build_pipeline(llm, llm, llm, llm, settings)

    assert pipeline is not None
    assert hasattr(pipeline, "ainvoke")


@pytest.mark.asyncio
async def test_pipeline_happy_path():
    market_llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    indicator_llm = mock_llm(_INDICATOR_RESPONSE)
    mock_llm(_PATTERN_RESPONSE)
    decision_llm = mock_llm(_DECISION_RESPONSE)

    # chart_vision_llm handles both pattern and trend agents
    vision_llm = mock_llm(_PATTERN_RESPONSE)

    settings = _make_settings(
        enable_indicator_agent=True,
        enable_pattern_agent=False,  # no chart_image_b64 provided
        enable_trend_agent=False,
    )

    pipeline = build_pipeline(market_llm, indicator_llm, vision_llm, decision_llm, settings)
    final_state = await pipeline.ainvoke(_make_initial_state())

    assert final_state["final_signal"] is not None
    assert final_state["final_signal"]["signal"] == "LONG"


@pytest.mark.asyncio
async def test_pipeline_partial_failure():
    """Pattern agent raises; pipeline still completes with final_signal."""
    market_llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    indicator_llm = mock_llm(_INDICATOR_RESPONSE)
    decision_llm = mock_llm(_DECISION_RESPONSE)

    # vision_llm raises to simulate a timeout
    failing_llm = MagicMock()
    failing_llm.ainvoke = AsyncMock(side_effect=Exception("vision timeout"))

    settings = _make_settings(
        enable_indicator_agent=True,
        enable_pattern_agent=True,
        enable_trend_agent=False,
    )

    pipeline = build_pipeline(market_llm, indicator_llm, failing_llm, decision_llm, settings)
    final_state = await pipeline.ainvoke(_make_initial_state())

    assert final_state["pattern_report"] is None
    assert final_state["final_signal"] is not None


@pytest.mark.asyncio
async def test_decision_node_retries_once_then_succeeds(monkeypatch):
    """execution_decision raising once (e.g. a transient API error) is retried
    once before giving up — the retry should succeed and produce a real signal."""
    import asyncio

    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    market_llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    indicator_llm = mock_llm(_INDICATOR_RESPONSE)

    decision_message = MagicMock()
    decision_message.content = json.dumps(_DECISION_RESPONSE)
    decision_llm = MagicMock()
    decision_llm.ainvoke = AsyncMock(
        side_effect=[Exception("temperature is deprecated for this model"), decision_message]
    )

    vision_llm = mock_llm(_PATTERN_RESPONSE)

    settings = _make_settings(
        enable_indicator_agent=True,
        enable_pattern_agent=False,
        enable_trend_agent=False,
    )

    pipeline = build_pipeline(market_llm, indicator_llm, vision_llm, decision_llm, settings)
    final_state = await pipeline.ainvoke(_make_initial_state())

    assert decision_llm.ainvoke.await_count == 2
    assert final_state["final_signal"]["signal"] == "LONG"
    assert "pipeline_error" not in final_state["final_signal"]["justification"]


@pytest.mark.asyncio
async def test_decision_node_falls_back_to_hold_after_retry_exhausted(monkeypatch):
    """execution_decision failing on both the first call and the retry surfaces
    a pipeline_error HOLD with the underlying exception message."""
    import asyncio

    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    market_llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    indicator_llm = mock_llm(_INDICATOR_RESPONSE)

    decision_llm = MagicMock()
    decision_llm.ainvoke = AsyncMock(side_effect=Exception("still broken"))

    vision_llm = mock_llm(_PATTERN_RESPONSE)

    settings = _make_settings(
        enable_indicator_agent=True,
        enable_pattern_agent=False,
        enable_trend_agent=False,
    )

    pipeline = build_pipeline(market_llm, indicator_llm, vision_llm, decision_llm, settings)
    final_state = await pipeline.ainvoke(_make_initial_state())

    assert decision_llm.ainvoke.await_count == 2
    assert final_state["final_signal"]["signal"] == "HOLD"
    assert final_state["final_signal"]["justification"] == "pipeline_error: still broken"


@pytest.mark.asyncio
async def test_pipeline_all_agents_enabled_end_to_end():
    """With all three sub-agents enabled and both chart images provided
    (the default configuration once enable_agent_pipeline=True), every
    node in the graph must actually execute and contribute a report."""
    market_llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    indicator_llm = mock_llm(_INDICATOR_RESPONSE)
    decision_llm = mock_llm(_DECISION_RESPONSE)

    # chart_vision_llm is shared by both pattern and trend agents in build_pipeline();
    # each call must resolve to a valid response regardless of which agent invokes it.
    vision_llm = mock_llm(_PATTERN_RESPONSE)

    settings = _make_settings(
        enable_indicator_agent=True,
        enable_pattern_agent=True,
        enable_trend_agent=True,
    )

    pipeline = build_pipeline(market_llm, indicator_llm, vision_llm, decision_llm, settings)
    state = _make_initial_state()
    state["chart_image_b64"] = "fake-base64-chart-data"
    state["trendline_chart_b64"] = "fake-base64-trendline-data"

    final_state = await pipeline.ainvoke(state)

    assert final_state["indicator_report"] is not None
    assert final_state["pattern_report"] is not None
    assert final_state["trend_report"] is not None
    assert final_state["final_signal"] is not None
    assert final_state["final_signal"]["signal"] == "LONG"
    # every node's token usage should be recorded for the pipeline trace/cost dashboard
    assert final_state["market_analysis_tokens"] is not None
    assert final_state["indicator_tokens"] is not None
    assert final_state["pattern_tokens"] is not None
    assert final_state["trend_tokens"] is not None
    assert final_state["decision_tokens"] is not None


@pytest.mark.asyncio
async def test_pipeline_disabled_indicator_agent():
    """With enable_indicator_agent=False, indicator_report stays None."""
    market_llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    indicator_llm = mock_llm(_INDICATOR_RESPONSE)
    vision_llm = mock_llm(_PATTERN_RESPONSE)
    decision_llm = mock_llm(_DECISION_RESPONSE)

    settings = _make_settings(
        enable_indicator_agent=False,
        enable_pattern_agent=False,
        enable_trend_agent=False,
    )

    pipeline = build_pipeline(market_llm, indicator_llm, vision_llm, decision_llm, settings)
    final_state = await pipeline.ainvoke(_make_initial_state())

    assert final_state["indicator_report"] is None


# ── Plan 05: ensemble/quorum voting ──────────────────────────────────────────

def test_indicator_vote_bullish_high_confidence():
    vote = _indicator_vote({"overall": "bullish", "confidence": "high"})
    assert vote == {"direction": "BUY", "confidence": 0.9}


def test_pattern_vote_bearish():
    vote = _pattern_vote({"bias": "bearish", "confidence": "medium"})
    assert vote == {"direction": "SELL", "confidence": 0.6}


def test_trend_vote_sideways_is_hold():
    vote = _trend_vote({"trend_prediction": "sideways", "confidence": "low"})
    assert vote == {"direction": "HOLD", "confidence": 0.3}


def test_vote_is_none_for_missing_report():
    assert _indicator_vote(None) is None
    assert _pattern_vote(None) is None
    assert _trend_vote(None) is None


def test_vote_is_none_for_parse_failure_marker():
    assert _indicator_vote({"overall": "neutral", "confidence": "low", "error": "parse_failed"}) is None


def test_quorum_verdict_majority_direction_calls_decision():
    votes = [
        {"direction": "BUY", "confidence": 0.9},
        {"direction": "BUY", "confidence": 0.6},
        {"direction": "HOLD", "confidence": 0.3},
    ]
    verdict = _quorum_verdict(votes)
    assert verdict["outcome"] == "call_decision"
    assert verdict["majority_direction"] == "BUY"
    assert verdict["majority_count"] == 2


def test_quorum_verdict_three_way_split_skips_decision():
    votes = [
        {"direction": "BUY", "confidence": 0.9},
        {"direction": "SELL", "confidence": 0.6},
        {"direction": "HOLD", "confidence": 0.3},
    ]
    verdict = _quorum_verdict(votes)
    assert verdict["outcome"] == "skip_hold"


def test_quorum_verdict_unanimous_hold_is_agreement():
    votes = [
        {"direction": "HOLD", "confidence": 0.3},
        {"direction": "HOLD", "confidence": 0.3},
        {"direction": "HOLD", "confidence": 0.3},
    ]
    verdict = _quorum_verdict(votes)
    assert verdict["outcome"] == "call_decision"
    assert verdict["majority_direction"] == "HOLD"


def test_quorum_verdict_insufficient_voters_calls_decision():
    verdict = _quorum_verdict([{"direction": "BUY", "confidence": 0.9}])
    assert verdict["outcome"] == "call_decision"
    assert verdict["reason"] == "insufficient_voters"


@pytest.mark.asyncio
async def test_pipeline_majority_agreement_calls_decision_agent_with_votes():
    """2/3 agreement (BUY, BUY, HOLD) — decision LLM must still be called,
    informed by the vote breakdown, per the plan's quorum design."""
    market_llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    indicator_llm = mock_llm({"overall": "bullish", "confidence": "high"})
    decision_llm = mock_llm(_DECISION_RESPONSE)
    # pattern agent votes BUY (bullish/high), trend agent votes HOLD (sideways/low) —
    # both share the vision_llm mock, so its single canned response must satisfy both.
    vision_llm = mock_llm({
        "bias": "bullish", "confidence": "high",
        "trend_prediction": "sideways",
        "pattern": "none", "completion_state": "forming",
    })

    settings = _make_settings(
        enable_indicator_agent=True, enable_pattern_agent=True, enable_trend_agent=True,
    )
    pipeline = build_pipeline(market_llm, indicator_llm, vision_llm, decision_llm, settings)
    state = _make_initial_state()
    state["chart_image_b64"] = "fake-chart"
    state["trendline_chart_b64"] = "fake-trendline"

    final_state = await pipeline.ainvoke(state)

    decision_llm.ainvoke.assert_awaited()
    assert final_state["vote_summary"]["outcome"] == "call_decision"
    assert final_state["vote_summary"]["majority_direction"] == "BUY"
    assert final_state["decision_tokens"] is not None
    assert final_state["final_signal"]["signal"] == "LONG"


@pytest.mark.asyncio
async def test_pipeline_three_way_split_skips_decision_agent():
    """BUY / SELL / HOLD with no majority — decision LLM must NOT be called,
    and the pipeline must resolve directly to HOLD at zero extra LLM cost."""
    market_llm = mock_llm(_MARKET_ANALYSIS_RESPONSE)
    indicator_llm = mock_llm({"overall": "bullish", "confidence": "high"})
    decision_llm = mock_llm(_DECISION_RESPONSE)
    vision_llm = mock_llm({
        "bias": "bearish", "confidence": "high",
        "trend_prediction": "sideways",
        "pattern": "none", "completion_state": "forming",
    })

    settings = _make_settings(
        enable_indicator_agent=True, enable_pattern_agent=True, enable_trend_agent=True,
    )
    pipeline = build_pipeline(market_llm, indicator_llm, vision_llm, decision_llm, settings)
    state = _make_initial_state()
    state["chart_image_b64"] = "fake-chart"
    state["trendline_chart_b64"] = "fake-trendline"

    final_state = await pipeline.ainvoke(state)

    decision_llm.ainvoke.assert_not_awaited()
    assert final_state["vote_summary"]["outcome"] == "skip_hold"
    assert final_state["decision_tokens"] is None
    assert final_state["final_signal"]["signal"] == "HOLD"
    assert final_state["final_signal"]["confidence"] == 0.0
