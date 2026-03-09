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
        logger.info(
            "Harmonic pattern found: %s %s on %s | quality=%.2f",
            best.pattern_name, best.direction, market_data.symbol, best.quality_score,
        )
        return to_signal(best, market_data)

    def analytics_schema(self) -> dict:
        return {
            "panel_type": "pattern_grid",
            "group_by": "pattern_name",
            "heatmap_axes": ["symbol", "pattern_name"],
            "metrics": ["trades", "win_rate", "profit_factor",
                        "total_pnl", "avg_win", "avg_loss"],
        }
