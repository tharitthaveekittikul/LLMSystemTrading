"""Tests for Williams Fractals pivot detection.

Key properties to verify:
  - Pivot high at index i: high[i] > high[i+-1] and high[i] > high[i+-2]
  - Non-repainting: pivot only returned when 2 candles after it have closed
  - Alternating: consecutive same-type pivots collapsed to most extreme
"""
from datetime import datetime, timezone, timedelta
import pytest
from services.mtf_data import OHLCV
from strategies.harmonic.swing_detector import find_pivots, Pivot


def _candle(high: float, low: float, t_offset: int = 0) -> OHLCV:
    t = datetime(2020, 1, 2, tzinfo=timezone.utc) + timedelta(minutes=t_offset * 15)
    mid = (high + low) / 2
    return OHLCV(time=t, open=mid, high=high, low=low, close=mid, tick_volume=100)


def _series(*high_low_pairs) -> list[OHLCV]:
    return [_candle(h, l, i) for i, (h, l) in enumerate(high_low_pairs)]


def test_find_pivot_high():
    # Pattern: ..., low, HIGH, low, low, low — high at index 2
    candles = _series(
        (1.0, 0.9), (1.1, 1.0),  # i=0,1
        (1.5, 1.1),               # i=2 — PIVOT HIGH (highest)
        (1.2, 1.0), (1.1, 0.9),  # i=3,4 — confirmed by 2 candles after
    )
    pivots = find_pivots(candles, n=2)
    highs = [p for p in pivots if p.type == "high"]
    assert len(highs) >= 1
    assert highs[0].price == 1.5


def test_find_pivot_low():
    # Pattern: ..., high, LOW, high, high, high
    candles = _series(
        (1.5, 1.3), (1.4, 1.2),  # i=0,1
        (1.2, 0.8),               # i=2 — PIVOT LOW (lowest low)
        (1.3, 1.0), (1.4, 1.1),  # i=3,4 — confirmed
    )
    pivots = find_pivots(candles, n=2)
    lows = [p for p in pivots if p.type == "low"]
    assert len(lows) >= 1
    assert lows[0].price == 0.8


def test_pivot_requires_n_candles_after_for_confirmation():
    """With n=2, pivot at index i requires candles i+1 and i+2 to exist."""
    # Only 3 candles — pivot at i=1 needs i+2=index 3, which doesn't exist
    candles = _series(
        (1.0, 0.9),
        (1.5, 1.0),  # would-be pivot high — NOT confirmed (only 1 candle after)
        (1.2, 1.0),
    )
    pivots = find_pivots(candles, n=2)
    # The peak at index 1 should NOT be returned (not enough candles after it)
    highs = [p for p in pivots if p.type == "high" and p.price == 1.5]
    assert len(highs) == 0


def test_no_pivots_in_flat_series():
    candles = _series(*[(1.0, 0.9)] * 10)
    pivots = find_pivots(candles, n=2)
    assert pivots == []


def test_pivot_dataclass_fields():
    candles = _series(
        (1.0, 0.9), (1.0, 0.9),
        (1.5, 0.8),   # both pivot high AND low in one candle? No — test separately
        (1.0, 0.9), (1.0, 0.9),
    )
    pivots = find_pivots(candles, n=2)
    for p in pivots:
        assert isinstance(p, Pivot)
        assert p.type in ("high", "low")
        assert isinstance(p.price, float)
        assert isinstance(p.index, int)
        assert isinstance(p.time, datetime)
