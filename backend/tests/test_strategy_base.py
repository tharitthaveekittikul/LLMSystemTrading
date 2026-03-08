import pytest
import asyncio
from datetime import datetime, timezone
from services.mtf_data import OHLCV, TimeframeData, MTFMarketData


def _make_md(symbol: str = "EURUSD") -> MTFMarketData:
    t = datetime(2020, 1, 2, tzinfo=timezone.utc)
    candles = [OHLCV(time=t, open=1.1, high=1.101, low=1.099, close=1.1, tick_volume=100)]
    return MTFMarketData(
        symbol=symbol, primary_tf="M15", current_price=1.1,
        timeframes={"M15": TimeframeData("M15", candles)},
        indicators={}, trigger_time=t,
    )


def test_rule_only_hold_returns_hold():
    from strategies.base_strategy import RuleOnlyStrategy

    class AlwaysHold(RuleOnlyStrategy):
        primary_tf = "M15"
        context_tfs = []
        symbols = ["EURUSD"]
        def check_rule(self, md): return None
        def analytics_schema(self): return {"panel_type": "pattern_grid"}

    result = asyncio.run(AlwaysHold().run(_make_md()))
    assert result.action == "HOLD"


@pytest.mark.asyncio
async def test_rule_only_returns_signal_from_check_rule():
    from strategies.base_strategy import RuleOnlyStrategy, StrategyResult

    class AlwaysBuy(RuleOnlyStrategy):
        primary_tf = "M15"
        context_tfs = []
        symbols = ["EURUSD"]
        def check_rule(self, md):
            return StrategyResult(action="BUY", entry=1.1, stop_loss=1.09,
                                  take_profit=1.12, confidence=0.9, rationale="test", timeframe="M15")
        def analytics_schema(self): return {}

    result = await AlwaysBuy().run(_make_md())
    assert result.action == "BUY"
    assert result.entry == 1.1


@pytest.mark.asyncio
async def test_rule_then_llm_holds_when_trigger_false():
    from strategies.base_strategy import RuleThenLLMStrategy

    class NoTrigger(RuleThenLLMStrategy):
        primary_tf = "M15"
        context_tfs = []
        symbols = ["EURUSD"]
        def check_trigger(self, md): return False
        def system_prompt(self): return "test"
        def analytics_schema(self): return {}

    result = await NoTrigger().run(_make_md())
    assert result.action == "HOLD"
    assert result.confidence == 0.0


def test_base_strategy_alias_works():
    from strategies.base_strategy import BaseStrategy, AbstractStrategy
    assert BaseStrategy is AbstractStrategy


def test_strategy_result_dataclass():
    from strategies.base_strategy import StrategyResult
    r = StrategyResult(action="BUY", entry=1.1, stop_loss=1.09, take_profit=1.12,
                       confidence=0.9, rationale="test", timeframe="M15")
    assert r.action == "BUY"
    assert r.pattern_name is None


def test_direction_from_action_strips_suffix():
    from strategies.base_strategy import direction_from_action
    assert direction_from_action("BUY") == "BUY"
    assert direction_from_action("SELL") == "SELL"
    assert direction_from_action("BUY_LIMIT") == "BUY"
    assert direction_from_action("SELL_LIMIT") == "SELL"
    assert direction_from_action("BUY_STOP") == "BUY"
    assert direction_from_action("SELL_STOP") == "SELL"
    assert direction_from_action("HOLD") == "HOLD"


def test_is_market_order():
    from strategies.base_strategy import is_market_order
    assert is_market_order("BUY") is True
    assert is_market_order("SELL") is True
    assert is_market_order("BUY_LIMIT") is False
    assert is_market_order("SELL_LIMIT") is False
    assert is_market_order("BUY_STOP") is False
    assert is_market_order("SELL_STOP") is False
    assert is_market_order("HOLD") is False


def test_strategy_result_accepts_pending_actions():
    from strategies.base_strategy import StrategyResult
    for action in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
        r = StrategyResult(
            action=action, entry=1.1, stop_loss=1.09,
            take_profit=1.12, confidence=0.8, rationale="test", timeframe="M15",
        )
        assert r.action == action


@pytest.mark.asyncio
async def test_multi_agent_consensus_uses_direction_not_exact_action():
    """Rule says BUY_LIMIT, LLM says BUY — same direction, should execute not HOLD."""
    from unittest.mock import AsyncMock, patch
    from strategies.base_strategy import MultiAgentStrategy, StrategyResult
    from ai.orchestrator import LLMAnalysisResult, LLMRoleResult, TradingSignal

    class TestMultiAgent(MultiAgentStrategy):
        primary_tf = "M15"
        context_tfs = ()
        symbols = ("EURUSD",)

        def check_rule(self, md):
            return StrategyResult(
                action="BUY_LIMIT", entry=1.09, stop_loss=1.08,
                take_profit=1.11, confidence=0.8, rationale="rule", timeframe="M15",
            )

        def system_prompt(self):
            return "test"

        def analytics_schema(self):
            return {}

    def _mock_role():
        return LLMRoleResult(
            content={}, input_tokens=0, output_tokens=0, total_tokens=0,
            model="gpt-4o", provider="openai", duration_ms=100,
        )

    llm_signal = TradingSignal(
        action="BUY", entry=1.09, stop_loss=1.08, take_profit=1.11,
        confidence=0.85, rationale="llm", timeframe="M15",
    )
    llm_analysis = LLMAnalysisResult(
        signal=llm_signal,
        market_analysis=_mock_role(),
        chart_vision=None,
        execution_decision=_mock_role(),
    )

    strategy = TestMultiAgent()
    md = _make_md()

    with patch("strategies.base_strategy.analyze_market", new=AsyncMock(return_value=llm_analysis)):
        result = await strategy.run(md)

    # Rule said BUY_LIMIT, LLM said BUY — same direction → use rule's result
    assert result.action == "BUY_LIMIT"
    assert result.entry == 1.09
