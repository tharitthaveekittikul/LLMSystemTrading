"""Signal Score Strategy — weighted indicator scoring with LLM validation.

Ported from the Nyao Scalper MQL5 EA (BSD-3-Clause, Elriz Wiraswara).
Adapted for M15/H1 timeframes and integrated into the RuleThenLLMStrategy framework.

Scoring components (max 10.0):
  Trend       (max 3.0) — EMA fast/slow alignment + slope direction
  Momentum    (max 3.0) — RSI sweet-spot + RSI breakout + body momentum × impulse
  Volatility  (max 4.0) — ATR chop filter + ATR expansion + 5-bar peak breakout
  Penalty              — wick rejection (opposing wick / body ratio)

Rule pre-filter: score >= min_score AND EMA-aligned direction
LLM validation: confirm entry / provide refined SL-TP
skip_llm mode:  fallback_rule_signal() returns ATR-based BUY/SELL directly
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from strategies.base_strategy import RuleThenLLMStrategy, StrategyResult

if TYPE_CHECKING:
    from services.mtf_data import OHLCV, MTFMarketData

logger = logging.getLogger(__name__)


# ── EMA / RSI / ATR helpers ────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> list[float]:
    """Compute EMA for a list of closing prices. Returns same-length list."""
    if not values or period <= 0:
        return values
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _rsi(closes: list[float], period: int) -> float:
    """Compute RSI(period) from the last (period+1) closes. Returns 0–100."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[-period - 1 + i] - closes[-period - 1 + i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(candles: list["OHLCV"], period: int) -> float:
    """Compute ATR(period) as simple average of true ranges."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        prev_close = candles[i - 1].close
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - prev_close),
            abs(candles[i].low - prev_close),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


# ── Strategy ───────────────────────────────────────────────────────────────────

class SignalScoreStrategy(RuleThenLLMStrategy):
    """Signal Score strategy (Nyao-inspired) for M15/H1.

    Rule pre-filter computes a 0–10 weighted score from EMA+RSI+ATR.
    If score >= min_score, passes to LLM for final entry validation.
    In skip_llm mode, falls back to rule-only ATR-based SL/TP.
    """

    primary_tf: str = "M15"
    context_tfs: tuple = ("H1",)
    candle_counts: dict = {"M15": 120, "H1": 60}
    symbols: tuple = ("XAUUSD",)

    # ── Optimizable parameters ────────────────────────────────────────────────
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    min_score: float = 5.5
    target_rr: float = 2.0

    # ── Cached state (per candle evaluation, not persisted) ───────────────────
    _last_score: float = 0.0
    _last_direction: str = "NONE"
    _last_ema_fast: float = 0.0
    _last_ema_slow: float = 0.0
    _last_rsi: float = 50.0
    _last_atr: float = 0.0

    # ── Score computation ─────────────────────────────────────────────────────

    def _compute_score(self, candles: list["OHLCV"]) -> tuple[float, str]:
        """Compute weighted signal score and direction from candle history.

        Returns (score: float, direction: "BUY" | "SELL" | "NONE").
        NONE is returned when score < min_score or insufficient data.
        """
        needed = max(self.ema_slow, self.rsi_period, self.atr_period) + 15
        if len(candles) < needed:
            return 0.0, "NONE"

        closes = [c.close for c in candles]
        opens = [c.open for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        # ── EMAs ──────────────────────────────────────────────────────────────
        ema_fast_series = _ema(closes, self.ema_fast)
        ema_slow_series = _ema(closes, self.ema_slow)
        ef_cur = ema_fast_series[-1]
        ef_prev = ema_fast_series[-2]
        es_cur = ema_slow_series[-1]

        self._last_ema_fast = ef_cur
        self._last_ema_slow = es_cur

        is_buy_trend = ef_cur > es_cur
        is_sell_trend = ef_cur < es_cur

        # ── Trend score (max 3.0) ─────────────────────────────────────────────
        trend_score = 0.0
        if is_buy_trend:
            trend_score += 1.5                          # alignment
            if ef_cur > ef_prev:
                trend_score += 1.5                      # slope rising
        elif is_sell_trend:
            trend_score += 1.5                          # alignment
            if ef_cur < ef_prev:
                trend_score += 1.5                      # slope falling

        # ── RSI ───────────────────────────────────────────────────────────────
        rsi = _rsi(closes, self.rsi_period)
        self._last_rsi = rsi

        # ── Momentum score (max 3.0) × impulse ───────────────────────────────
        momentum = 0.0
        if is_buy_trend:
            if 50 < rsi < 80:
                momentum += 1.0                         # RSI sweet-spot
            if rsi > 60:
                momentum += 0.5                         # RSI breakout
        elif is_sell_trend:
            if 20 < rsi < 50:
                momentum += 1.0
            if rsi < 40:
                momentum += 0.5

        cur_body = abs(closes[-1] - opens[-1])
        lookback = min(10, len(candles) - 1)
        avg_body = sum(abs(closes[-i] - opens[-i]) for i in range(1, lookback + 1)) / lookback
        if cur_body > avg_body:
            momentum += 1.5                             # body momentum

        # Impulse multiplier: body acceleration + directional continuity
        body_accel = (cur_body / avg_body) if avg_body > 0 else 1.0
        consec = 1
        for i in range(1, min(3, len(candles) - 1)):
            if is_buy_trend and closes[-1 - i] > opens[-1 - i]:
                consec += 1
            elif is_sell_trend and closes[-1 - i] < opens[-1 - i]:
                consec += 1
            else:
                break
        impulse = min(body_accel - 1.0, 0.5) + (consec - 1) * 0.1
        momentum_score = momentum * (1.0 + max(impulse, 0.0))

        # ── ATR ───────────────────────────────────────────────────────────────
        atr_cur = _atr(candles, self.atr_period)
        atr_prev = _atr(candles[:-1], self.atr_period) if len(candles) > self.atr_period + 2 else atr_cur
        self._last_atr = atr_cur

        atr_ratio = (atr_cur / atr_prev) if atr_prev > 0 else 1.0

        # Chop filter (max 2.0)
        if atr_ratio > 1.2:
            chop_score = 2.0                            # strong trend
        elif atr_ratio > 0.9:
            chop_score = 1.0                            # weak trend
        else:
            chop_score = 0.5                            # chop risk

        # ATR expansion bonus
        vol_score = 1.0 if atr_ratio > 1.2 else 0.0

        # Peak breakout (5-bar)
        recent_high = max(highs[-6:-1])
        recent_low = min(lows[-6:-1])
        peak_score = 0.0
        if is_buy_trend and closes[-1] > recent_high:
            peak_score = 1.0
        elif is_sell_trend and closes[-1] < recent_low:
            peak_score = 1.0

        volatility_score = chop_score + vol_score + peak_score

        # ── Wick penalty ──────────────────────────────────────────────────────
        candle_range = highs[-1] - lows[-1]
        penalty = 0.0
        if candle_range > 0 and cur_body > 0:
            if is_buy_trend:
                upper_wick = highs[-1] - max(closes[-1], opens[-1])
                penalty = min(upper_wick / cur_body, 1.0)
            elif is_sell_trend:
                lower_wick = min(closes[-1], opens[-1]) - lows[-1]
                penalty = min(lower_wick / cur_body, 1.0)

        # ── Final score ───────────────────────────────────────────────────────
        raw = trend_score + min(momentum_score, 3.0) + min(volatility_score, 4.0)
        score = max(raw - penalty, 0.0)

        if score < self.min_score:
            return score, "NONE"

        direction = "BUY" if is_buy_trend else ("SELL" if is_sell_trend else "NONE")
        return score, direction

    # ── RuleThenLLMStrategy interface ─────────────────────────────────────────

    def check_trigger(self, market_data: "MTFMarketData") -> bool:
        tf_data = market_data.timeframes.get(self.primary_tf)
        if not tf_data or not tf_data.candles:
            return False
        score, direction = self._compute_score(tf_data.candles)
        self._last_score = score
        self._last_direction = direction
        return direction != "NONE"

    def system_prompt(self) -> str:
        return (
            f"You are a professional trading analyst validating a technical signal.\n\n"
            f"The rule-based system detected a {self._last_direction} signal on {self.primary_tf} "
            f"with a rule signal score of {self._last_score:.1f}/10.0.\n\n"
            f"Indicators at signal time:\n"
            f"  EMA({self.ema_fast}) = {self._last_ema_fast:.4f}\n"
            f"  EMA({self.ema_slow}) = {self._last_ema_slow:.4f}\n"
            f"  RSI({self.rsi_period}) = {self._last_rsi:.1f}\n"
            f"  ATR({self.atr_period}) = {self._last_atr:.4f}\n\n"
            f"Validate whether current price action, structure, and momentum support "
            f"this {self._last_direction} entry. If the signal is valid, provide entry price, "
            f"stop-loss (below/above recent swing), and take-profit at {self.target_rr}R. "
            f"If conditions have deteriorated, return HOLD with rationale."
        )

    def fallback_rule_signal(self, market_data: "MTFMarketData") -> StrategyResult | None:
        """Rule-only signal for skip_llm mode (optimization sweeps).

        Uses ATR-based SL/TP and EMA direction determined by check_trigger().
        """
        if self._last_direction == "NONE" or self._last_atr == 0.0:
            return None

        tf_data = market_data.timeframes.get(self.primary_tf)
        if not tf_data or not tf_data.candles:
            return None

        price = tf_data.candles[-1].close
        atr = self._last_atr

        if self._last_direction == "BUY":
            sl = price - atr
            tp = price + atr * self.target_rr
        else:
            sl = price + atr
            tp = price - atr * self.target_rr

        return StrategyResult(
            action=self._last_direction,
            entry=price,
            stop_loss=round(sl, 5),
            take_profit=round(tp, 5),
            confidence=min(self._last_score / 10.0, 1.0),
            rationale=(
                f"Signal score {self._last_score:.1f}/10.0 — "
                f"EMA{self.ema_fast}({'>' if self._last_direction == 'BUY' else '<'})EMA{self.ema_slow}, "
                f"RSI={self._last_rsi:.1f}, ATR={atr:.4f}"
            ),
            timeframe=self.primary_tf,
            pattern_name="signal_score",
            pattern_metadata={
                "score": round(self._last_score, 2),
                "direction": self._last_direction,
                "ema_fast": round(self._last_ema_fast, 4),
                "ema_slow": round(self._last_ema_slow, 4),
                "rsi": round(self._last_rsi, 1),
                "atr": round(atr, 4),
            },
        )

    def analytics_schema(self) -> dict:
        return {"panel_type": "pattern_grid", "group_by": "pattern_name"}
