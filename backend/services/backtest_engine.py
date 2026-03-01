"""BacktestEngine — event-driven simulation of a trading strategy on OHLCV history.

Design:
  - Iterates candles chronologically one at a time (event-driven, not vectorised).
  - Calls strategy.generate_signal(market_data) at each candle using the same
    interface as live trading — no strategy code changes required.
  - Two fill modes:
      close_price:  entry and SL/TP checks at candle close
      intra_candle: entry at next open + spread; SL/TP checked during candle H/L
  - LLM strategies are sampled: LLM called every N-th candle (budget = max_llm_calls).
  - One open position per symbol at a time (matching live behaviour).
  - progress_cb(pct: int) is called every 1_000 candles if provided.
"""
from __future__ import annotations

import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Number of candles in the rolling window passed to strategy.generate_signal()
_WINDOW = 50


class BacktestEngine:

    async def run(
        self,
        candles: list[dict],
        strategy,
        config: dict,
        progress_cb: Callable[[int], Awaitable[None]] | None,
    ) -> dict:
        """Run the backtest simulation.

        Args:
            candles:     Chronological list of OHLCV candle dicts.
            strategy:    Any object with .generate_signal(market_data) -> dict | None
                         and .strategy_type (str: "code" | "config" | "prompt").
            config:      {symbol, timeframe, initial_balance, spread_pips,
                         execution_mode, volume, max_llm_calls}
            progress_cb: Optional async callback(pct: int) called every 1_000 candles.

        Returns:
            {trades: list[dict], equity_curve: list[dict]}
        """
        symbol = config["symbol"]
        timeframe = config["timeframe"]
        balance = config["initial_balance"]
        spread = config.get("spread_pips", 1.5) * _pip_value(symbol)
        mode = config.get("execution_mode", "close_price")
        volume = config.get("volume", 0.1)
        max_llm = config.get("max_llm_calls", 100)
        total = len(candles)

        # LLM sampling step: call LLM every K-th candle
        is_llm_strategy = getattr(strategy, "strategy_type", "code") in ("config", "prompt")
        llm_step = max(1, total // max_llm) if is_llm_strategy and max_llm > 0 else None

        open_position: dict | None = None  # one position at a time
        trades: list[dict] = []
        equity_curve: list[dict] = []
        last_signal: dict | None = None

        for i, candle in enumerate(candles):
            # ── 1. Check open position SL/TP ──────────────────────────────────
            if open_position is not None:
                closed = _check_exit(open_position, candle, mode)
                if closed:
                    profit = _calc_profit(open_position, closed["exit_price"], volume, symbol)
                    balance += profit
                    trade = {**open_position, **closed, "profit": round(profit, 4),
                             "equity_after": round(balance, 4)}
                    trades.append(trade)
                    equity_curve.append({"time": closed["exit_time"], "equity": round(balance, 4)})
                    open_position = None

            # ── 2. Generate signal ─────────────────────────────────────────────
            if open_position is None and i >= _WINDOW - 1:
                window = candles[max(0, i - _WINDOW + 1): i + 1]
                market_data = _build_market_data(symbol, timeframe, candle, window)

                # For LLM strategies, only call on sampled candles; hold last signal between
                if is_llm_strategy and llm_step and (i % llm_step != 0):
                    signal = last_signal
                else:
                    try:
                        signal = strategy.generate_signal(market_data)
                    except Exception as exc:
                        logger.warning("generate_signal error at candle %d: %s", i, exc)
                        signal = None
                    last_signal = signal

                # ── 3. Open new position ───────────────────────────────────────
                if signal and signal.get("action") in ("BUY", "SELL"):
                    fill_price = _fill_price(signal, candle, candles, i, mode, spread)
                    if fill_price is not None:
                        open_position = {
                            "symbol": symbol,
                            "direction": signal["action"],
                            "entry_time": candle["time"],
                            "entry_price": round(fill_price, 5),
                            "stop_loss": round(signal["stop_loss"], 5),
                            "take_profit": round(signal["take_profit"], 5),
                            "volume": volume,
                            "exit_time": None,
                            "exit_price": None,
                            "exit_reason": None,
                            "profit": None,
                            "equity_after": None,
                        }

            # ── 4. Progress callback ───────────────────────────────────────────
            if progress_cb and i % 1000 == 0 and i > 0:
                pct = int(i / total * 100)
                await progress_cb(pct)

        # ── Close any open position at end of data ─────────────────────────────
        if open_position is not None:
            last_candle = candles[-1]
            profit = _calc_profit(open_position, last_candle["close"], volume, symbol)
            balance += profit
            trade = {
                **open_position,
                "exit_time": last_candle["time"],
                "exit_price": round(last_candle["close"], 5),
                "exit_reason": "end_of_data",
                "profit": round(profit, 4),
                "equity_after": round(balance, 4),
            }
            trades.append(trade)
            equity_curve.append({"time": last_candle["time"], "equity": round(balance, 4)})

        logger.info(
            "Backtest complete | %d candles | %d trades | final_equity=%.2f",
            total, len(trades), balance,
        )
        return {"trades": trades, "equity_curve": equity_curve}


# ── Private helpers ────────────────────────────────────────────────────────────

def _pip_value(symbol: str) -> float:
    """Convert 1 pip to price units. JPY pairs use 0.01, others 0.0001."""
    return 0.01 if "JPY" in symbol else 0.0001


def _check_exit(pos: dict, candle: dict, mode: str) -> dict | None:
    """Return exit info dict or None if position stays open."""
    direction = pos["direction"]
    sl = pos["stop_loss"]
    tp = pos["take_profit"]
    t = candle["time"]

    if mode == "close_price":
        price = candle["close"]
        if direction == "BUY":
            if price <= sl:
                return {"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
            if price >= tp:
                return {"exit_time": t, "exit_price": tp, "exit_reason": "tp"}
        else:  # SELL
            if price >= sl:
                return {"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
            if price <= tp:
                return {"exit_time": t, "exit_price": tp, "exit_reason": "tp"}
    else:  # intra_candle
        high, low = candle["high"], candle["low"]
        open_p = candle["open"]
        if direction == "BUY":
            sl_hit = low <= sl
            tp_hit = high >= tp
            if sl_hit and tp_hit:
                return ({"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
                        if abs(open_p - sl) <= abs(open_p - tp)
                        else {"exit_time": t, "exit_price": tp, "exit_reason": "tp"})
            if sl_hit:
                return {"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
            if tp_hit:
                return {"exit_time": t, "exit_price": tp, "exit_reason": "tp"}
        else:  # SELL
            sl_hit = high >= sl
            tp_hit = low <= tp
            if sl_hit and tp_hit:
                return ({"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
                        if abs(open_p - sl) <= abs(open_p - tp)
                        else {"exit_time": t, "exit_price": tp, "exit_reason": "tp"})
            if sl_hit:
                return {"exit_time": t, "exit_price": sl, "exit_reason": "sl"}
            if tp_hit:
                return {"exit_time": t, "exit_price": tp, "exit_reason": "tp"}
    return None


def _fill_price(
    signal: dict, candle: dict, candles: list, i: int, mode: str, spread: float
) -> float | None:
    """Determine fill price based on execution mode."""
    if mode == "close_price":
        return candle["close"]
    # intra_candle: fill at next open + spread (for BUY) or - spread (for SELL)
    if i + 1 < len(candles):
        next_open = candles[i + 1]["open"]
        return next_open + spread if signal["action"] == "BUY" else next_open - spread
    return None  # no next candle, skip


def _calc_profit(pos: dict, exit_price: float, volume: float, symbol: str) -> float:
    """Calculate P&L in account currency (1 lot = 100,000 units)."""
    contract_size = 100_000
    entry = pos["entry_price"]
    direction_sign = 1 if pos["direction"] == "BUY" else -1
    price_diff = (exit_price - entry) * direction_sign
    return price_diff * volume * contract_size


def _build_market_data(symbol: str, timeframe: str, candle: dict, window: list[dict]) -> dict:
    """Build the market_data dict expected by strategy.generate_signal()."""
    closes = [c["close"] for c in window]
    sma_20 = sum(closes[-20:]) / min(20, len(closes))
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": candle["close"],
        "candles": window,
        "indicators": {
            "sma_20": round(sma_20, 5),
            "recent_high": max(c["high"] for c in window),
            "recent_low": min(c["low"] for c in window),
            "candle_count": len(window),
        },
        "open_positions": [],
        "recent_signals": [],
    }
