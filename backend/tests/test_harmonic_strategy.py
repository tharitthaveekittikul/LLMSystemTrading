"""Integration test: HarmonicStrategy.run() returns a StrategyResult."""
import asyncio
from datetime import datetime, timezone, timedelta
from services.mtf_data import OHLCV, TimeframeData, MTFMarketData


def _flat_candles(n: int, price: float = 1.1, tf_minutes: int = 15) -> list[OHLCV]:
    t = datetime(2020, 1, 2, tzinfo=timezone.utc)
    result = []
    for i in range(n):
        result.append(OHLCV(time=t + timedelta(minutes=i * tf_minutes),
                             open=price, high=price + 0.001, low=price - 0.001,
                             close=price, tick_volume=100))
    return result


def _make_md(m15_candles=None, h1_candles=None) -> MTFMarketData:
    t = datetime(2020, 1, 2, tzinfo=timezone.utc)
    m15 = m15_candles or _flat_candles(50)
    h1  = h1_candles  or _flat_candles(20, tf_minutes=60)
    return MTFMarketData(
        symbol="XAUUSD", primary_tf="M15", current_price=m15[-1].close,
        timeframes={"M15": TimeframeData("M15", m15), "H1": TimeframeData("H1", h1)},
        indicators={}, trigger_time=t,
    )


def test_harmonic_strategy_holds_on_no_pattern():
    from strategies.harmonic.harmonic_strategy import HarmonicStrategy
    strategy = HarmonicStrategy()
    result = asyncio.run(strategy.run(_make_md()))
    # Flat candles have no pivots → HOLD
    assert result.action == "HOLD"


def test_harmonic_strategy_analytics_schema():
    from strategies.harmonic.harmonic_strategy import HarmonicStrategy
    schema = HarmonicStrategy().analytics_schema()
    assert schema["panel_type"] == "pattern_grid"
    assert schema["group_by"] == "pattern_name"


def test_harmonic_strategy_execution_mode():
    from strategies.harmonic.harmonic_strategy import HarmonicStrategy
    assert HarmonicStrategy.execution_mode == "rule_only"
