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

    # Configurable parameters
    target_rr: float = 2.0  # Take profit Risk:Reward ratio based on sweep size

    def apply_db_config(self, strategy_db: "Strategy") -> None:
        super().apply_db_config(strategy_db)
        
        # Ensure we have enough context candles for the reference timeframe
        counts = {self.primary_tf: 20} # We usually don't need too many primary candles for the scan
        
        # We need at least 2 completed context candles (one to act as the reference, 
        # and checking the prior one to ensure we have historical data)
        for tf in self.context_tfs:
            counts[tf] = 5 
            
        self.candle_counts = counts

    def check_rule(self, market_data: MTFMarketData) -> StrategyResult | None:
        primary_data = market_data.timeframes.get(self.primary_tf)
        if not primary_data or len(primary_data.candles) < 2:
            return None

        # The user's input clarified that the "reference_tf" is essentially the context_tf.
        # So we use the first context_tf as our reference timeframe (e.g., H4 or D1).
        if not self.context_tfs:
            logger.warning("CRTStrategy requires at least one context_tfs (e.g., H4) to act as the reference timeframe.")
            return None
            
        reference_tf = self.context_tfs[0]
        ref_data = market_data.timeframes.get(reference_tf)
        
        # We need at least one completed reference candle
        if not ref_data or not ref_data.candles:
            return None

        # The latest completed reference candle defines our range
        ref_candle = ref_data.candles[-1]
        ref_high = ref_candle.high
        ref_low = ref_candle.low
        
        # We only care about primary candles that occurred AFTER the reference candle closed (in a real scenario,
        # MTFMarketData already ensures `candles` are completed. The reference_tf candle[-1] is the *last closed* candle
        # of that timeframe, meaning the *current* open reference candle is forming right now, and the primary
        # candles are forming inside it).
        
        # To find a sweep and reclaim, we look at the most recent primary candle that just closed.
        last_primary = primary_data.candles[-1]
        
        # If the last closed primary candle is still outside the range, or hasn't swept, we do nothing.
        # We need to find if there was a recent sweep that has now been reclaimed.
        
        # We'll look back through recent primary candles (since the reference candle closed)
        # to see if a sweep occurred, and if the *last* candle confirmed the reclaim.
        
        # Gather primary candles that occurred after the reference candle opened
        # (Technically after the *previous* reference candle closed, so during the *current* reference candle's formation).
        # Since ref_candle is the *last closed*, its time is when it opened.
        # Wait, if ref_candle is the last closed H4, then the *current* time is after ref_candle.time + 4H.
        # Let's just find the max/min of primary candles since the reference candle closed.
        
        # Time when the ref_candle closed (approximate, depending on your system's exact OHLCV timestamp semantics. 
        # Usually `time` is the open time. But we can just use the latest sequence of primary candles.)
        # Let's assume we are monitoring the *current* forming reference candle's range. 
        # Actually CRT usually uses the *previous* period's range (e.g. Previous Daily High/Low).
        # Since ref_candle is the last *closed* candle, it is exactly the "previous" period.
        
        sweep_high = -float('inf')
        sweep_low = float('inf')
        has_swept_high = False
        has_swept_low = False
        
        # Check primary candles that opened AFTER or AT the same time the new reference period started.
        # This properly handles backtesting semantics where the ref_candle.time represents the start of the period.
        relevant_primary_candles = [c for c in primary_data.candles if c.time >= ref_candle.time]
        
        if not relevant_primary_candles:
            return None
            
        # Scan for sweeps in the current period
        for c in relevant_primary_candles:
            if c.high > ref_high:
                has_swept_high = True
                sweep_high = max(sweep_high, c.high)
            if c.low < ref_low:
                has_swept_low = True
                sweep_low = min(sweep_low, c.low)
                
        # Now check if the *most recent* closed primary candle just reclaimed the range.
        current_close = last_primary.close
        
        # Bullish CRT: Swept Low, then reclaimed (closed back above ref_low)
        bullish_reclaim = has_swept_low and current_close > ref_low
        
        # Bearish CRT: Swept High, then reclaimed (closed back below ref_high)
        bearish_reclaim = has_swept_high and current_close < ref_high
        
        # To avoid entering multiple times after a sweep, we should ideally check if the *previous* primary candle
        # was still below/above the range (the actual moment of crossing).
        # For simplicity, if the last candle closed inside, and a sweep happened, we trigger.
        # A stricter check: only trigger if the *previous* candle closed outside, and *this* candle closed inside.
        if len(relevant_primary_candles) >= 2:
            prev_primary = relevant_primary_candles[-2]
            bullish_trigger = has_swept_low and prev_primary.close <= ref_low and current_close > ref_low
            bearish_trigger = has_swept_high and prev_primary.close >= ref_high and current_close < ref_high
        else:
            # Not enough candles to confirm the moment of crossing
            bullish_trigger = False
            bearish_trigger = False
            
        if bullish_trigger and not bearish_trigger:
            # Calculate Risk & Reward
            entry_price = current_close
            stop_loss = sweep_low # Stop loss at the absolute bottom of the sweep
            
            # Avoid divide by zero or negative risk
            if stop_loss >= entry_price:
                return None
                
            range_size = ref_high - ref_low
            tp1 = entry_price + (range_size * 0.5)
            tp2 = ref_high # Opposite extreme of reference range
            
            # If for some reason TP2 is lower than TP1 (e.g., massive sweep), prioritize TP1
            if tp2 <= tp1:
                tp2 = tp1 + (entry_price - stop_loss)
            
            return StrategyResult(
                action="BUY",
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=tp2, # Fallback single TP is the extreme
                take_profit_levels=[tp1, tp2],
                confidence=0.85,
                rationale=f"Bullish CRT: Swept {reference_tf} Low ({ref_low}) to {sweep_low} and reclaimed.",
                timeframe=self.primary_tf,
                pattern_name="CRT_Bullish_Sweep"
            )
            
        elif bearish_trigger and not bullish_trigger:
            # Calculate Risk & Reward
            entry_price = current_close
            stop_loss = sweep_high # Stop loss at the absolute top of the sweep
            
            if stop_loss <= entry_price:
                return None
                
            range_size = ref_high - ref_low
            tp1 = entry_price - (range_size * 0.5)
            tp2 = ref_low # Opposite extreme of reference range
            
            # If for some reason TP2 is higher than TP1, prioritize TP1
            if tp2 >= tp1:
                tp2 = tp1 - (stop_loss - entry_price)
            
            return StrategyResult(
                action="SELL",
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=tp2,
                take_profit_levels=[tp1, tp2],
                confidence=0.85,
                rationale=f"Bearish CRT: Swept {reference_tf} High ({ref_high}) to {sweep_high} and reclaimed.",
                timeframe=self.primary_tf,
                pattern_name="CRT_Bearish_Sweep"
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
