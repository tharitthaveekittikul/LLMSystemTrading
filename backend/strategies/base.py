"""BaseStrategy — base class for code-driven trading strategies.

Subclasses that implement generate_signal() bypass the LLM entirely and perform
pure rule-based signal generation in Python.

Subclasses that only override system_prompt() still use the LLM, but with a
custom system message instead of the default one.

──────────────────────────────────────────────────────────────────────────────
Example 1: Pure rule-based (no LLM, no API cost)

    from strategies.base import BaseStrategy

    class SmaCrossover(BaseStrategy):
        symbols = ["EURUSD", "GBPUSD"]

        def lot_size(self)   -> float | None: return 0.01
        def sl_pips(self)    -> float | None: return 20
        def tp_pips(self)    -> float | None: return 40
        def news_filter(self) -> bool:        return True

        def generate_signal(self, market_data: dict) -> dict | None:
            candles = market_data["candles"]
            sma5  = sum(c["close"] for c in candles[-5:])  / 5
            sma20 = sum(c["close"] for c in candles[-20:]) / 20
            price = market_data["current_price"]
            tf    = market_data["timeframe"]

            if sma5 > sma20:
                return {
                    "action":      "BUY",
                    "entry":       price,
                    "stop_loss":   round(price - 0.0020, 5),
                    "take_profit": round(price + 0.0040, 5),
                    "confidence":  0.75,
                    "rationale":   f"SMA5 {sma5:.5f} crossed above SMA20 {sma20:.5f}",
                    "timeframe":   tf,
                }
            if sma5 < sma20:
                return {
                    "action":      "SELL",
                    "entry":       price,
                    "stop_loss":   round(price + 0.0020, 5),
                    "take_profit": round(price - 0.0040, 5),
                    "confidence":  0.75,
                    "rationale":   f"SMA5 {sma5:.5f} crossed below SMA20 {sma20:.5f}",
                    "timeframe":   tf,
                }
            return None  # no clear crossover → treated as HOLD, no order placed

──────────────────────────────────────────────────────────────────────────────
Example 2: LLM with a custom system prompt

    class ConservativeScalper(BaseStrategy):
        symbols = ["EURUSD"]

        def system_prompt(self) -> str | None:
            return "You are a conservative forex scalper. Only signal BUY/SELL on
            very clear setups with confluence across multiple indicators..."

        # No generate_signal → falls back to the LLM with this system prompt.

──────────────────────────────────────────────────────────────────────────────
market_data dict passed to generate_signal():

    symbol          str
    timeframe       str
    current_price   float
    candles         list[dict]  50 OHLCV dicts, oldest→newest
                                keys: time, open, high, low, close, tick_volume
    indicators      dict        precomputed: sma_20, recent_high, recent_low, candle_count
    open_positions  list[dict]  keys: symbol, direction, volume, profit
    recent_signals  list[dict]  keys: symbol, signal, confidence, rationale

generate_signal() return dict (all keys required):

    action          "BUY" | "SELL" | "HOLD"
    entry           float
    stop_loss       float
    take_profit     float
    confidence      float  (0.0 – 1.0)
    rationale       str
    timeframe       str

Return None to skip the rule-based path and fall back to the LLM instead.
"""
from __future__ import annotations


class BaseStrategy:
    """Base class for code-type trading strategies.

    Override generate_signal() to bypass the LLM with rule-based logic.
    Override system_prompt() to customise the LLM system message (only used
    when generate_signal() is not overridden or returns None).
    """

    symbols: list[str] = []

    def lot_size(self) -> float | None:
        return None

    def sl_pips(self) -> float | None:
        return None

    def tp_pips(self) -> float | None:
        return None

    def news_filter(self) -> bool:
        return True

    def system_prompt(self) -> str | None:
        return None

    def generate_signal(self, _market_data: dict) -> dict | None:
        """Compute a trading signal from market data without calling the LLM.

        Return a dict with keys: action, entry, stop_loss, take_profit,
        confidence, rationale, timeframe.

        Return None to fall back to LLM analysis (using system_prompt() if set).
        Subclasses name the parameter market_data (without underscore).
        """
        return None  # default: always delegate to the LLM; subclasses override this
