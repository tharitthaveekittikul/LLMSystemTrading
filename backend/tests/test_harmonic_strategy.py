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


# ── TDD: prz_calculator must emit BUY_LIMIT / SELL_LIMIT (not BUY / SELL) ────

def _make_bullish_gartley_pattern():
    """Return a minimal PatternResult for a bullish Gartley at known prices."""
    from strategies.harmonic.swing_detector import Pivot
    from strategies.harmonic.patterns.base_pattern import PatternResult

    t0 = datetime(2020, 1, 2, tzinfo=timezone.utc)
    x = Pivot(index=0, time=t0 + timedelta(hours=0), price=1.500, type="high")
    a = Pivot(index=1, time=t0 + timedelta(hours=1), price=1.000, type="low")
    b = Pivot(index=2, time=t0 + timedelta(hours=2), price=1.309, type="high")
    c = Pivot(index=3, time=t0 + timedelta(hours=3), price=1.191, type="low")
    d = Pivot(index=4, time=t0 + timedelta(hours=4), price=1.107, type="low")
    return PatternResult(
        pattern_name="Gartley",
        direction="bullish",
        points={"X": x, "A": a, "B": b, "C": c, "D": d},
        ratios={"AB_XA": 0.618, "BC_AB": 0.382, "CD_BC": 0.712, "D_XA": 0.786},
        expected_ratios={},
        ratio_accuracy=0.95,
        quality_score=0.85,
        prz_high=1.115,
        prz_low=1.100,
    )


def _make_bearish_gartley_pattern():
    """Return a minimal PatternResult for a bearish Gartley at known prices."""
    from strategies.harmonic.swing_detector import Pivot
    from strategies.harmonic.patterns.base_pattern import PatternResult

    t0 = datetime(2020, 1, 2, tzinfo=timezone.utc)
    x = Pivot(index=0, time=t0 + timedelta(hours=0), price=1.000, type="low")
    a = Pivot(index=1, time=t0 + timedelta(hours=1), price=1.500, type="high")
    b = Pivot(index=2, time=t0 + timedelta(hours=2), price=1.191, type="low")
    c = Pivot(index=3, time=t0 + timedelta(hours=3), price=1.309, type="high")
    d = Pivot(index=4, time=t0 + timedelta(hours=4), price=1.393, type="high")
    return PatternResult(
        pattern_name="Gartley",
        direction="bearish",
        points={"X": x, "A": a, "B": b, "C": c, "D": d},
        ratios={"AB_XA": 0.618, "BC_AB": 0.382, "CD_BC": 0.712, "D_XA": 0.786},
        expected_ratios={},
        ratio_accuracy=0.95,
        quality_score=0.85,
        prz_high=1.400,
        prz_low=1.385,
    )


def test_prz_calculator_bullish_emits_buy_limit():
    """prz_calculator.to_signal() for a bullish pattern must produce BUY_LIMIT, not BUY."""
    from strategies.harmonic.prz_calculator import to_signal
    pattern = _make_bullish_gartley_pattern()
    md = _make_md()
    result = to_signal(pattern, md)
    assert result.action == "BUY_LIMIT", (
        f"Expected 'BUY_LIMIT' but got '{result.action}'. "
        "Harmonic entries wait at the D-point PRZ — use a limit order."
    )


def test_prz_calculator_bearish_emits_sell_limit():
    """prz_calculator.to_signal() for a bearish pattern must produce SELL_LIMIT, not SELL."""
    from strategies.harmonic.prz_calculator import to_signal
    pattern = _make_bearish_gartley_pattern()
    md = _make_md()
    result = to_signal(pattern, md)
    assert result.action == "SELL_LIMIT", (
        f"Expected 'SELL_LIMIT' but got '{result.action}'. "
        "Harmonic entries wait at the D-point PRZ — use a limit order."
    )
