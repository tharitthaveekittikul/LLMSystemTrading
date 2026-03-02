# backend/strategies/hmm_strategy.py
"""HMM Regime-Gated Strategy — BaseStrategy subclass."""
from __future__ import annotations

from strategies.base_strategy import BaseStrategy


class HMMRegimeStrategy(BaseStrategy):
    """Returns HOLD during high_volatility; otherwise falls through to LLM
    (which receives regime context in its prompt from Step 5.5).

    Register in the UI:
        type=Code, module=strategies.hmm_strategy, class=HMMRegimeStrategy
    """
    def system_prompt(self) -> str:
        return (
            "You are a regime-aware trading analyst. "
            "The market data context includes the current HMM regime. "
            "Only BUY in bullish regimes, only SELL in bearish regimes, "
            "scalp both directions when ranging, and always HOLD in high-volatility regimes."
        )

    def generate_signal(self, market_data: dict) -> dict | None:
        candles = market_data.get("candles", [])
        symbol  = market_data.get("symbol")
        tf      = market_data.get("timeframe")

        if len(candles) < 50:
            return None

        try:
            from services.hmm_service import HMMService
            svc    = HMMService(symbol=symbol, timeframe=tf)
            regime = svc.predict(candles)
        except Exception:
            return None

        if regime["regime"] == "high_volatility":
            return {
                "action":      "HOLD",
                "entry":       market_data.get("current_price", 0.0),
                "stop_loss":   0.0,
                "take_profit": 0.0,
                "confidence":  1.0,
                "rationale":   "HMM regime: high_volatility — no new trades",
                "timeframe":   tf,
            }

        return None  # LLM path — regime injected into prompt by Step 5.5
