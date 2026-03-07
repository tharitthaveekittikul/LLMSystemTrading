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
