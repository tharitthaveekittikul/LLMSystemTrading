from datetime import datetime, timezone, timedelta
from services.mtf_data import OHLCV
from strategies.harmonic.swing_detector import find_pivots


def _candle(high, low, t_offset=0):
    t = datetime(2020, 1, 2, tzinfo=timezone.utc) + timedelta(minutes=t_offset * 15)
    mid = (high + low) / 2
    return OHLCV(time=t, open=mid, high=high, low=low, close=mid, tick_volume=100)


def test_scanner_returns_list():
    from strategies.harmonic.pattern_scanner import scan
    candles = [_candle(1.0 + 0.01 * i % 3, 0.9 + 0.01 * i % 2, i) for i in range(30)]
    result = scan(find_pivots(candles, n=2))
    assert isinstance(result, list)


def test_prz_calculator_returns_strategy_result():
    from strategies.harmonic.patterns.base_pattern import PatternResult
    from strategies.harmonic.swing_detector import Pivot
    from strategies.harmonic.prz_calculator import to_signal
    from services.mtf_data import TimeframeData, MTFMarketData

    t = datetime(2020, 1, 2, tzinfo=timezone.utc)
    d_pivot = Pivot(index=4, time=t, price=1.107, type="low")
    x_pivot = Pivot(index=0, time=t, price=1.500, type="high")
    pattern = PatternResult(
        pattern_name="Gartley", direction="bullish",
        points={"X": x_pivot, "D": d_pivot, "A": Pivot(1, t, 1.0, "low"),
                "B": Pivot(2, t, 1.309, "high"), "C": Pivot(3, t, 1.191, "low")},
        ratios={}, expected_ratios={}, ratio_accuracy=0.9,
        quality_score=0.85, prz_high=1.110, prz_low=1.105,
    )
    candles = [_candle(1.1 + 0.001 * i, 1.09, i) for i in range(20)]
    md = MTFMarketData(
        symbol="EURUSD", primary_tf="M15", current_price=1.107,
        timeframes={"M15": TimeframeData("M15", candles)},
        indicators={}, trigger_time=t,
    )
    result = to_signal(pattern, md)
    assert result.action in ("BUY_LIMIT", "SELL_LIMIT")
    assert result.stop_loss is not None
    assert result.take_profit is not None
    assert result.pattern_name == "Gartley"
