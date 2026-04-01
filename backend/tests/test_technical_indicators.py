import random

import pytest

pandas_ta = pytest.importorskip("pandas_ta")
mplfinance = pytest.importorskip("mplfinance")

from services.technical_indicators import (
    compute_indicators,
    fit_trendlines,
    render_trendline_chart,
)


def make_ohlcv(n=60):
    from datetime import datetime, timedelta
    price = 1.1000
    candles = []
    base = datetime(2024, 1, 1)
    for i in range(n):
        open_ = price
        high = open_ + random.uniform(0, 0.002)
        low = open_ - random.uniform(0, 0.002)
        close = random.uniform(low, high)
        candles.append(
            {
                "time": (base + timedelta(hours=i)).isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": random.randint(100, 1000),
            }
        )
        price = close
    return candles


INDICATOR_KEYS = {
    "rsi",
    "macd_line",
    "macd_signal",
    "macd_histogram",
    "stoch_k",
    "stoch_d",
    "roc",
    "willr",
}


def test_compute_indicators_basic():
    candles = make_ohlcv(60)
    result = compute_indicators(candles)

    assert isinstance(result, dict)
    assert INDICATOR_KEYS == set(result.keys()), (
        f"Missing keys: {INDICATOR_KEYS - set(result.keys())}"
    )
    for key, value in result.items():
        assert isinstance(value, float), f"Expected float for {key}, got {type(value)}"


def test_compute_indicators_integer_timestamps():
    """MT5 copy_rates_from_pos() returns Unix integer timestamps — must not crash."""
    candles = make_ohlcv(60)
    from datetime import datetime
    base_ts = int(datetime(2024, 1, 1).timestamp())
    for i, c in enumerate(candles):
        c["time"] = base_ts + i * 3600  # integer Unix seconds
    result = compute_indicators(candles)
    assert isinstance(result, dict)
    assert INDICATOR_KEYS == set(result.keys())


def test_compute_indicators_too_few_candles():
    candles = make_ohlcv(30)
    with pytest.raises(ValueError):
        compute_indicators(candles)


def test_fit_trendlines_returns_tuple():
    candles = make_ohlcv(60)
    high = [c["high"] for c in candles]
    low = [c["low"] for c in candles]
    close = [c["close"] for c in candles]

    result = fit_trendlines(high, low, close, lookback=50)

    assert isinstance(result, tuple)
    assert len(result) == 4
    for val in result:
        assert isinstance(val, float), f"Expected float, got {type(val)}"


def test_render_trendline_chart_returns_base64():
    candles = make_ohlcv(60)
    high = [c["high"] for c in candles]
    low = [c["low"] for c in candles]
    close = [c["close"] for c in candles]

    s_slope, s_int, r_slope, r_int = fit_trendlines(high, low, close, lookback=50)
    result = render_trendline_chart(
        candles, s_slope, s_int, r_slope, r_int, lookback=50
    )

    assert isinstance(result, str)
    assert len(result) > 0
