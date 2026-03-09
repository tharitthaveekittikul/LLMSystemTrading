"""Pattern scanner — tests all 7 harmonic patterns against a pivot list.

Slides a 5-pivot window over the most recent pivots and tests each pattern.
Returns all valid patterns sorted by quality_score descending.
"""
from __future__ import annotations

import logging
from strategies.harmonic.swing_detector import Pivot
from strategies.harmonic.patterns.base_pattern import PatternResult
from strategies.harmonic.patterns.abcd import ABCD
from strategies.harmonic.patterns.bat import Bat
from strategies.harmonic.patterns.butterfly import Butterfly
from strategies.harmonic.patterns.crab import Crab
from strategies.harmonic.patterns.cypher import Cypher
from strategies.harmonic.patterns.gartley import Gartley
from strategies.harmonic.patterns.shark import Shark
from services.mtf_data import OHLCV

logger = logging.getLogger(__name__)

_XABCD_PATTERNS = [Gartley(), Bat(), Butterfly(), Crab(), Cypher(), ABCD()]
_SHARK = Shark()
_MAX_PIVOTS_TO_SCAN = 20   # only scan recent pivots for performance


def scan(
    pivots: list[Pivot],
    min_pattern_pips: float = 0.0,
    trend_candles: list[OHLCV] | None = None,
) -> list[PatternResult]:
    """Scan pivot list for all 7 harmonic patterns.

    Args:
        pivots:           Confirmed pivot list from find_pivots().
        min_pattern_pips: Minimum XA leg size in price units (0 = no filter).
        trend_candles:    Optional higher-timeframe candles for trend alignment scoring.

    Returns:
        All valid patterns sorted by quality_score descending.
    """
    if len(pivots) < 5:
        return []

    recent = pivots[-_MAX_PIVOTS_TO_SCAN:]
    results: list[PatternResult] = []

    # Slide 5-pivot window for XABCD patterns
    for i in range(len(recent) - 4):
        window = recent[i: i + 5]
        x, a, b, c, d = window

        xa_size = abs(a.price - x.price)
        if min_pattern_pips > 0 and xa_size < min_pattern_pips:
            continue

        for pattern in _XABCD_PATTERNS:
            result = pattern.validate(x, a, b, c, d)
            if result is not None:
                result.quality_score = _quality_score(result, xa_size, trend_candles)
                results.append(result)

    # Slide 5-pivot window for Shark (uses OXABC)
    for i in range(len(recent) - 4):
        window = recent[i: i + 5]
        o, x, a, b, c = window
        result = _SHARK.validate(o, x, a, b, c)
        if result is not None:
            ox_size = abs(x.price - o.price)
            result.quality_score = _quality_score(result, ox_size, trend_candles)
            results.append(result)

    results.sort(key=lambda r: r.quality_score, reverse=True)
    logger.debug("Pattern scan: %d pivots → %d patterns found", len(pivots), len(results))
    return results


def _quality_score(
    result: PatternResult,
    ref_leg_size: float,
    trend_candles: list[OHLCV] | None,
) -> float:
    """Compute quality score: ratio_accuracy × size_score × trend_alignment."""
    # Size score: larger pattern (in price) = more significant; normalise to 0-1
    size_score = min(1.0, ref_leg_size / 0.01)   # 0.01 price units = max score for forex

    trend_alignment = 1.0
    if trend_candles and len(trend_candles) >= 5:
        # Simple trend: compare last 5 higher-TF closes
        closes = [c.close for c in trend_candles[-5:]]
        trend_up = closes[-1] > closes[0]
        if result.direction == "bullish" and trend_up:
            trend_alignment = 1.2
        elif result.direction == "bearish" and not trend_up:
            trend_alignment = 1.2

    return result.ratio_accuracy * size_score * trend_alignment
