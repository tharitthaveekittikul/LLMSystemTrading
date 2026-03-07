"""PRZ (Potential Reversal Zone) calculator.

Given a confirmed PatternResult, computes:
  - Entry price: D point (or C for Shark)
  - Stop loss: beyond X point ± ATR(14) × multiplier
  - Take profit 1: 0.382 retracement of CD leg
  - Take profit 2: 0.618 retracement of CD leg (use TP1 as default)
"""
from __future__ import annotations

from strategies.harmonic.patterns.base_pattern import PatternResult
from services.mtf_data import MTFMarketData, OHLCV


def _atr(candles: list[OHLCV], period: int = 14) -> float:
    """Compute Average True Range over last `period` candles."""
    if len(candles) < 2:
        return 0.001
    trs = []
    for i in range(1, min(period + 1, len(candles))):
        c = candles[i]
        prev_close = candles[i - 1].close
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.001


def to_signal(
    pattern: PatternResult,
    market_data: MTFMarketData,
    atr_multiplier_sl: float = 0.5,
):
    """Convert a PatternResult to a StrategyResult with entry, SL, TP."""
    from strategies.base_strategy import StrategyResult, _HOLD

    primary_candles = market_data.timeframes.get(market_data.primary_tf)
    candle_list = primary_candles.candles if primary_candles else []
    atr_value = _atr(candle_list)

    points = pattern.points
    d = points.get("D") or points.get("C")   # Shark uses C as entry
    x = points.get("X") or points.get("O")   # Shark uses O as origin
    c_point = points.get("C")
    a_point = points.get("A")

    if d is None or x is None:
        return _HOLD

    entry = d.price
    is_bullish = pattern.direction == "bullish"

    # Stop loss: beyond X point (the origin of the pattern)
    sl_buffer = atr_value * atr_multiplier_sl
    stop_loss = x.price - sl_buffer if is_bullish else x.price + sl_buffer

    # Take profit: 0.382 retracement of the CD leg (conservative target)
    if c_point is not None:
        cd_size = abs(d.price - c_point.price)
        tp1 = entry + cd_size * 0.382 if is_bullish else entry - cd_size * 0.382
    elif a_point is not None:
        tp1 = a_point.price   # fall back to A level
    else:
        tp1 = entry + atr_value * 2 if is_bullish else entry - atr_value * 2

    action = "BUY" if is_bullish else "SELL"

    return StrategyResult(
        action=action,
        entry=round(entry, 5),
        stop_loss=round(stop_loss, 5),
        take_profit=round(tp1, 5),
        confidence=round(pattern.quality_score, 3),
        rationale=(
            f"{pattern.pattern_name} {pattern.direction} | "
            f"ratio_accuracy={pattern.ratio_accuracy:.2f} | "
            f"PRZ={pattern.prz_low:.5f}-{pattern.prz_high:.5f}"
        ),
        timeframe=market_data.primary_tf,
        pattern_name=pattern.pattern_name,
        pattern_metadata={
            "direction": pattern.direction,
            "ratios": pattern.ratios,
            "ratio_accuracy": pattern.ratio_accuracy,
            "quality_score": pattern.quality_score,
            "prz_high": pattern.prz_high,
            "prz_low": pattern.prz_low,
            "points": {k: {"price": v.price, "time": v.time.isoformat(), "type": v.type}
                       for k, v in pattern.points.items()},
        },
    )
