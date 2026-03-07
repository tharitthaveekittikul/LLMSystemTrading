"""Williams Fractals pivot detection.

A pivot HIGH at index i is confirmed when:
    candle[i].high > candle[i-n..i-1].high  AND  candle[i].high > candle[i+1..i+n].high

A pivot LOW at index i is confirmed when:
    candle[i].low < candle[i-n..i-1].low  AND  candle[i].low < candle[i+1..i+n].low

Default n=2 (5-bar fractal — standard for harmonic trading).
Non-repainting: a pivot at i is only returned after candles i+1..i+n have closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from services.mtf_data import OHLCV


@dataclass
class Pivot:
    index: int
    time: datetime
    price: float
    type: Literal["high", "low"]


def find_pivots(candles: list[OHLCV], n: int = 2) -> list[Pivot]:
    """Return confirmed pivot highs and lows from a candle list.

    Args:
        candles: List of OHLCV candles sorted oldest->newest.
        n:       Number of candles required on each side for confirmation.
                 Default 2 -> 5-bar Williams Fractal (industry standard).

    Returns:
        List of Pivot objects, ordered by index. Consecutive same-type pivots
        are NOT deduplicated here — caller (pattern_scanner) handles that.
    """
    if len(candles) < 2 * n + 1:
        return []

    pivots: list[Pivot] = []
    # Only test candles where n candles exist on both sides (i=n..len-n-1)
    # Confirmed = i+n < len(candles), so we stop at len-n-1
    for i in range(n, len(candles) - n):
        c = candles[i]
        left_highs = [candles[j].high for j in range(i - n, i)]
        right_highs = [candles[j].high for j in range(i + 1, i + n + 1)]
        left_lows = [candles[j].low for j in range(i - n, i)]
        right_lows = [candles[j].low for j in range(i + 1, i + n + 1)]

        is_pivot_high = c.high > max(left_highs) and c.high > max(right_highs)
        is_pivot_low = c.low < min(left_lows) and c.low < min(right_lows)

        if is_pivot_high:
            pivots.append(Pivot(index=i, time=c.time, price=c.high, type="high"))
        if is_pivot_low:
            pivots.append(Pivot(index=i, time=c.time, price=c.low, type="low"))

    # Sort by index (a candle can be both a pivot high and low in extreme cases)
    pivots.sort(key=lambda p: (p.index, p.type))
    return pivots
