"""HarmonicStrategy — RuleOnlyStrategy using Williams Fractals + all 7 harmonic patterns.

Registration in DB:
  name: "Harmonic Patterns"
  execution_mode: "rule_only"
  module_path: "strategies.harmonic.harmonic_strategy"
  class_name: "HarmonicStrategy"
  primary_tf: "M15"
  context_tfs: ["H1", "M1"]
"""
from __future__ import annotations

import logging
from strategies.base_strategy import RuleOnlyStrategy, StrategyResult
from services.mtf_data import MTFMarketData

logger = logging.getLogger(__name__)


class HarmonicStrategy(RuleOnlyStrategy):
    execution_mode = "rule_only"

    # Configurable parameters
    fractal_n: int = 2              # Williams Fractals confirmation candles each side
    min_pattern_pips: float = 0.0   # minimum XA leg (0 = no filter)
    prz_cooldown_candles: int = 20  # suppress re-entry into same PRZ for N primary-TF candles
    prz_tolerance_pct: float = 0.005  # PRZ "same zone" threshold (0.5%)

    def apply_db_config(self, strategy_db: "Strategy") -> None:
        super().apply_db_config(strategy_db)
        counts = {self.primary_tf: 50}
        for tf in self.context_tfs:
            counts[tf] = 20  # Normally H1/M1 need ~20 candles context
        self.candle_counts = counts

    def check_rule(self, market_data: MTFMarketData) -> StrategyResult | None:
        from strategies.harmonic.swing_detector import find_pivots
        from strategies.harmonic.pattern_scanner import scan
        from strategies.harmonic.prz_calculator import to_signal

        # Lazy-init PRZ cooldown state (survives across candles within one backtest run)
        if not hasattr(self, "_prz_candle_count"):
            self._prz_candle_count: int = 0
            self._last_entry_price: float | None = None
            self._last_entry_candle: int = -999
        self._prz_candle_count += 1

        primary_data = market_data.timeframes.get(self.primary_tf)
        if not primary_data or len(primary_data.candles) < 10:
            return None

        # Try to use the first context timeframe (usually H1) for trend alignment
        trend_tf = self.context_tfs[0] if self.context_tfs else None
        trend_data = market_data.timeframes.get(trend_tf) if trend_tf else None
        trend_candles = trend_data.candles if trend_data else None

        pivots = find_pivots(primary_data.candles, n=self.fractal_n)
        if len(pivots) < 5:
            logger.debug("Not enough pivots (%d) for pattern scan on %s",
                         len(pivots), market_data.symbol)
            return None

        patterns = scan(pivots, min_pattern_pips=self.min_pattern_pips,
                        trend_candles=trend_candles)
        if not patterns:
            return None

        best = patterns[0]
        result = to_signal(best, market_data)
        if result is None:
            return None

        # PRZ cooldown: don't re-enter the same price zone within cooldown window.
        # Prevents the engine from re-trading the same harmonic pattern repeatedly
        # after a quick TP hit while the same pivots are still in the rolling window.
        if self._last_entry_price is not None and result.entry is not None:
            price_diff_pct = abs(result.entry - self._last_entry_price) / self._last_entry_price
            candles_since = self._prz_candle_count - self._last_entry_candle
            if price_diff_pct < self.prz_tolerance_pct and candles_since < self.prz_cooldown_candles:
                logger.debug(
                    "PRZ cooldown: skipping %s re-entry at %.5f (%.2f%% from last, %d/%d candles elapsed)",
                    best.pattern_name, result.entry,
                    price_diff_pct * 100, candles_since, self.prz_cooldown_candles,
                )
                return None

        self._last_entry_price = result.entry
        self._last_entry_candle = self._prz_candle_count
        logger.info(
            "Harmonic pattern found: %s %s on %s | quality=%.2f",
            best.pattern_name, best.direction, market_data.symbol, best.quality_score,
        )
        return result

    def analytics_schema(self) -> dict:
        return {
            "panel_type": "pattern_grid",
            "group_by": "pattern_name",
            "heatmap_axes": ["symbol", "pattern_name"],
            "metrics": ["trades", "win_rate", "profit_factor",
                        "total_pnl", "avg_win", "avg_loss"],
        }
