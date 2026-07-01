"""ORBStrategy — RuleOnlyStrategy using Opening Range Breakout (ORB).

Translated from GOLD_ORB MQL5 EA (price_action.mqh → Open_Range_Breakout()).

Registration in DB:
  name: "Opening Range Breakout (ORB)"
  execution_mode: "rule_only"
  module_path: "strategies.orb.orb_strategy"
  class_name: "ORBStrategy"
  primary_tf: "H1"
  context_tfs: []

Strategy logic:
  1. At session open (start_hour server time), the first H1 candle defines the
     initial range high/low.
  2. Each subsequent candle either extends the range (resetting the consecutive
     in-range counter) or consolidates inside it (incrementing the counter).
  3. Once the consecutive-in-range count reaches candle_composition the range
     is "final" (locked in from that side).
  4. A close above the locked range_high → BUY.
     A close below the locked range_low  → SELL.
  5. Optional MA filter: long only above SMA(ma_period), short only below it.

SL/TP differ from the original EA's fixed 400/1200 pts:
  risk   = distance from entry to the opposite range boundary
  TP     = entry ± risk × target_rr   (default 3.0 ≈ 1200/400 original ratio)
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from services.mtf_data import MTFMarketData
from strategies.base_strategy import RuleOnlyStrategy, StrategyResult

if TYPE_CHECKING:
    from db.models import Strategy

logger = logging.getLogger(__name__)


class ORBStrategy(RuleOnlyStrategy):
    execution_mode = "rule_only"

    # ── Configurable parameters (loaded from strategy_params JSON via base apply_db_config) ──

    start_hour: int = 1
    """Server-time hour when the trading session opens (gold market ≈ 01:00).
    Session candles are those whose open time hour >= start_hour on the trigger date."""

    candle_composition: int = 3
    """Minimum consecutive H1 candles that must stay inside the range (without
    extending it) before the range is considered final on that side.
    Translated from PriceActionORB_CandleComposition in the MQL5 EA."""

    target_rr: float = 3.0
    """Risk:Reward ratio for take-profit. TP = entry ± risk × target_rr.
    Default 3.0 matches the original EA's hardcoded TP=1200 / SL=400."""

    use_ma_filter: bool = True
    """When True, apply a Simple Moving Average filter: BUY only if close > SMA,
    SELL only if close < SMA. Mirrors the MA100 filter in the original EA."""

    ma_period: int = 100
    """Period for the SMA filter (100 = default from the original EA)."""

    min_range_pts: float = 0.0
    """Minimum range size (range_high − range_low) in price units to accept the
    setup. Filters sessions with very tight, insignificant ranges."""

    def apply_db_config(self, strategy_db: "Strategy") -> None:
        # Base class loads primary_tf, context_tfs, symbols, skip filters, and
        # strategy_params JSON → setattr for all params above.
        super().apply_db_config(strategy_db)

        # Need enough H1 candles: MA period + buffer for current-day session candles.
        self.candle_counts = {"H1": max(self.ma_period + 20, 120)}

    def check_rule(self, market_data: MTFMarketData) -> StrategyResult | None:
        # ── 1. Get H1 candles ────────────────────────────────────────────────
        h1_data = market_data.timeframes.get("H1")
        if not h1_data or len(h1_data.candles) < 2:
            return None

        all_candles = h1_data.candles  # sorted oldest → newest

        # ── 2. Filter to today's session candles ─────────────────────────────
        # trigger_time is UTC close time of the latest H1 candle.
        trigger_date: date = market_data.trigger_time.date()

        session = [
            c for c in all_candles
            if c.time.date() == trigger_date and c.time.hour >= self.start_hour
        ]

        # Need: at least 1 range-builder candle + 1 trigger candle.
        # With candle_composition=3 we need min 5: 1 init + 3 composing + 1 trigger.
        min_required = 1 + self.candle_composition + 1
        if len(session) < min_required:
            return None

        # ── 3. Split range candles / trigger candle ───────────────────────────
        trigger_candle = session[-1]
        range_candles = session[:-1]

        # ── 4. Build range state (translated from Open_Range_Breakout) ────────
        # First candle of the session initialises range_high / range_low.
        range_high: float = range_candles[0].high
        range_low: float = range_candles[0].low

        # Counters: how many consecutive candles at the *end* of range_candles
        # stayed inside without extending the range from that side.
        consec_below_high: int = 0  # → resistance locked when >= candle_composition
        consec_above_low: int = 0   # → support locked when >= candle_composition

        for candle in range_candles[1:]:
            if candle.high > range_high:
                # Extended resistance — range not final yet on the high side.
                range_high = candle.high
                consec_below_high = 0
            else:
                consec_below_high += 1

            if candle.low < range_low:
                # Extended support — range not final yet on the low side.
                range_low = candle.low
                consec_above_low = 0
            else:
                consec_above_low += 1

        # ── 5. Range finalisation ─────────────────────────────────────────────
        high_locked = consec_below_high >= self.candle_composition
        low_locked = consec_above_low >= self.candle_composition

        if not high_locked and not low_locked:
            return None

        # ── 6. Minimum range filter ───────────────────────────────────────────
        range_size = range_high - range_low
        if self.min_range_pts > 0 and range_size < self.min_range_pts:
            return None

        # ── 7. Entry conditions ───────────────────────────────────────────────
        entry = trigger_candle.close

        bullish_trigger = low_locked and entry > range_high
        bearish_trigger = high_locked and entry < range_low

        if bullish_trigger and bearish_trigger:
            return None  # ambiguous — skip

        # ── 8. Optional MA filter ─────────────────────────────────────────────
        if self.use_ma_filter and len(all_candles) >= self.ma_period:
            closes = [c.close for c in all_candles[-self.ma_period:]]
            ma_value = sum(closes) / len(closes)
            if bullish_trigger and entry <= ma_value:
                return None
            if bearish_trigger and entry >= ma_value:
                return None

        # ── 9. Construct StrategyResult ───────────────────────────────────────
        if bullish_trigger:
            stop_loss = range_low
            if stop_loss >= entry:
                return None
            risk = entry - stop_loss
            take_profit = entry + risk * self.target_rr
            return StrategyResult(
                action="BUY",
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.80,
                rationale=(
                    f"ORB Bullish breakout: session range {range_low:.5f}–{range_high:.5f} "
                    f"(size={range_size:.5f}), close {entry:.5f} broke above resistance. "
                    f"Comp={consec_below_high}/{self.candle_composition}, RR={self.target_rr}"
                ),
                timeframe="H1",
                pattern_name="ORB_Bullish",
                pattern_metadata={
                    "range_high": range_high,
                    "range_low": range_low,
                    "range_size": range_size,
                    "candle_composition": self.candle_composition,
                    "consec_above_low": consec_above_low,
                    "start_hour": self.start_hour,
                    "session_candles": len(session),
                },
            )

        if bearish_trigger:
            stop_loss = range_high
            if stop_loss <= entry:
                return None
            risk = stop_loss - entry
            take_profit = entry - risk * self.target_rr
            return StrategyResult(
                action="SELL",
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.80,
                rationale=(
                    f"ORB Bearish breakdown: session range {range_low:.5f}–{range_high:.5f} "
                    f"(size={range_size:.5f}), close {entry:.5f} broke below support. "
                    f"Comp={consec_above_low}/{self.candle_composition}, RR={self.target_rr}"
                ),
                timeframe="H1",
                pattern_name="ORB_Bearish",
                pattern_metadata={
                    "range_high": range_high,
                    "range_low": range_low,
                    "range_size": range_size,
                    "candle_composition": self.candle_composition,
                    "consec_below_high": consec_below_high,
                    "start_hour": self.start_hour,
                    "session_candles": len(session),
                },
            )

        return None

    def analytics_schema(self) -> dict:
        return {
            "panel_type": "pattern_grid",
            "group_by": "pattern_name",
            "heatmap_axes": ["symbol", "pattern_name"],
            "metrics": ["trades", "win_rate", "profit_factor",
                        "total_pnl", "avg_win", "avg_loss"],
        }
