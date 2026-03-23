"""CRTStrategy — RuleOnlyStrategy using Candle Range Theory (CRT).

Registration in DB:
  name: "Candle Range Theory"
  execution_mode: "rule_only"
  module_path: "strategies.crt.crt_strategy"
  class_name: "CRTStrategy"
  primary_tf: "M15"
  context_tfs: ["H4"]
"""
from __future__ import annotations

import logging
from strategies.base_strategy import RuleOnlyStrategy, StrategyResult
from services.mtf_data import MTFMarketData

logger = logging.getLogger(__name__)


class CRTStrategy(RuleOnlyStrategy):
    execution_mode = "rule_only"

    # ── Configurable parameters (loaded from strategy_params JSON via base apply_db_config) ──
    target_rr: float = 2.0
    """Risk:Reward ratio. TP = entry ± (entry - SL) × target_rr."""

    sweep_buffer_pips: float = 0.0
    """Extra price units beyond the range boundary required to count as a real sweep.
    Filters noise wicks that barely poke beyond the range. Units are raw price
    (approximate pips; for XAUUSD use ~0.1–0.5, for FX majors use ~0.0001–0.0003)."""

    min_range_pips: float = 0.0
    """Minimum reference candle range size (price units) to consider the setup valid.
    Filters tiny, low-significance reference candles."""

    max_candles_after_sweep: int = 10
    """Maximum number of primary-TF candles after the first sweep to still accept a
    reclaim signal. Prevents acting on stale setups."""

    def apply_db_config(self, strategy_db: "Strategy") -> None:
        # Base class loads primary_tf, context_tfs, symbols, skip filters, and
        # strategy_params JSON → setattr for all params above.
        super().apply_db_config(strategy_db)

        # Ensure enough candles are fetched for the scan
        counts = {self.primary_tf: max(self.max_candles_after_sweep + 5, 20)}
        for tf in self.context_tfs:
            counts[tf] = 5
        self.candle_counts = counts

    def check_rule(self, market_data: MTFMarketData) -> StrategyResult | None:
        primary_data = market_data.timeframes.get(self.primary_tf)
        if not primary_data or len(primary_data.candles) < 2:
            return None

        if not self.context_tfs:
            logger.warning("CRTStrategy requires at least one context_tf (e.g., H4).")
            return None

        reference_tf = self.context_tfs[0]
        ref_data = market_data.timeframes.get(reference_tf)
        if not ref_data or not ref_data.candles:
            return None

        # Last closed reference candle defines the range
        ref_candle = ref_data.candles[-1]
        ref_high = ref_candle.high
        ref_low = ref_candle.low

        # Filter: ignore tiny reference candles
        ref_range = ref_high - ref_low
        if ref_range < self.min_range_pips:
            return None

        # Primary candles inside the current reference period
        relevant = [c for c in primary_data.candles if c.time >= ref_candle.time]
        if len(relevant) < 2:
            return None

        # ── Sweep detection ───────────────────────────────────────────────────
        sweep_high_threshold = ref_high + self.sweep_buffer_pips
        sweep_low_threshold = ref_low - self.sweep_buffer_pips

        sweep_high_price = -float("inf")
        sweep_low_price = float("inf")
        first_sweep_high_idx: int | None = None
        first_sweep_low_idx: int | None = None

        for idx, c in enumerate(relevant):
            if c.high > sweep_high_threshold:
                sweep_high_price = max(sweep_high_price, c.high)
                if first_sweep_high_idx is None:
                    first_sweep_high_idx = idx
            if c.low < sweep_low_threshold:
                sweep_low_price = min(sweep_low_price, c.low)
                if first_sweep_low_idx is None:
                    first_sweep_low_idx = idx

        has_swept_high = first_sweep_high_idx is not None
        has_swept_low = first_sweep_low_idx is not None

        # ── Staleness filter ──────────────────────────────────────────────────
        last_idx = len(relevant) - 1
        if has_swept_high and (last_idx - first_sweep_high_idx) > self.max_candles_after_sweep:
            has_swept_high = False
        if has_swept_low and (last_idx - first_sweep_low_idx) > self.max_candles_after_sweep:
            has_swept_low = False

        # ── Reclaim trigger: wick swept the boundary, current candle closes back inside ──
        # CRT sweep = wick (high/low) crosses boundary; close is typically still inside.
        # We only need: sweep detected + current close reclaims inside the range.
        current = relevant[-1]
        current_close = current.close

        bullish_trigger = (
            has_swept_low
            and current_close > ref_low
        )
        bearish_trigger = (
            has_swept_high
            and current_close < ref_high
        )

        # Avoid ambiguous simultaneous signals
        if bullish_trigger and bearish_trigger:
            return None

        if bullish_trigger:
            entry = current_close
            stop_loss = sweep_low_price
            if stop_loss >= entry:
                return None
            risk = entry - stop_loss
            tp1 = entry + ref_range * 0.5
            tp2 = entry + risk * self.target_rr
            # Take the farther of the two as the primary TP
            take_profit = max(tp1, tp2)
            return StrategyResult(
                action="BUY",
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                take_profit_levels=[tp1, tp2],
                confidence=0.85,
                rationale=(
                    f"Bullish CRT: swept {reference_tf} low {ref_low:.5f} → {sweep_low_price:.5f}, "
                    f"reclaimed. RR={self.target_rr}"
                ),
                timeframe=self.primary_tf,
                pattern_name="CRT_Bullish_Sweep",
            )

        if bearish_trigger:
            entry = current_close
            stop_loss = sweep_high_price
            if stop_loss <= entry:
                return None
            risk = stop_loss - entry
            tp1 = entry - ref_range * 0.5
            tp2 = entry - risk * self.target_rr
            take_profit = min(tp1, tp2)
            return StrategyResult(
                action="SELL",
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                take_profit_levels=[tp1, tp2],
                confidence=0.85,
                rationale=(
                    f"Bearish CRT: swept {reference_tf} high {ref_high:.5f} → {sweep_high_price:.5f}, "
                    f"reclaimed. RR={self.target_rr}"
                ),
                timeframe=self.primary_tf,
                pattern_name="CRT_Bearish_Sweep",
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
