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
  - New AbstractStrategy subclasses (with primary_tf attribute) are detected
    automatically and dispatched via await strategy.run(MTFMarketData).
"""
from __future__ import annotations

import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Number of candles in the rolling window passed to strategy.generate_signal()
_WINDOW = 50


def _dict_to_ohlcv(d: dict):
    from services.mtf_data import OHLCV
    return OHLCV(
        time=d["time"], open=d["open"], high=d["high"],
        low=d["low"], close=d["close"], tick_volume=d.get("tick_volume", 0),
    )


def _build_indicators(window: list[dict]) -> dict:
    closes = [c["close"] for c in window]
    sma_20 = sum(closes[-20:]) / min(20, len(closes))
    return {
        "sma_20": round(sma_20, 5),
        "recent_high": max(c["high"] for c in window),
        "recent_low": min(c["low"] for c in window),
    }


def _strategy_result_to_dict(result) -> dict | None:
    """Convert StrategyResult to the dict format BacktestEngine uses internally."""
    if result is None or result.action == "HOLD":
        return None
    return {
        "action": result.action,
        "entry": result.entry,
        "stop_loss": result.stop_loss,
        "take_profit": result.take_profit,
        "confidence": result.confidence,
        "rationale": result.rationale,
        "timeframe": result.timeframe,
        "pattern_name": result.pattern_name,
        "pattern_metadata": result.pattern_metadata,
    }


class BacktestEngine:

    async def run(
        self,
        candles: list[dict],
        strategy,
        config: dict,
        progress_cb: Callable[[int], Awaitable[None]] | None,
        context_candles: dict[str, list[dict]] | None = None,
    ) -> dict:
        """Run the backtest simulation.

        Args:
            candles:         Chronological list of primary-TF OHLCV candle dicts.
            strategy:        Any object with .generate_signal(market_data) -> dict | None
                             and .strategy_type (str: "code" | "config" | "prompt").
            config:          {symbol, timeframe, initial_balance, spread_pips,
                             execution_mode, volume, max_llm_calls}
            progress_cb:     Optional async callback(pct: int) called every 1_000 candles.
            context_candles: Optional dict of {tf_name: candle_list} for MTF strategies.

        Returns:
            {trades: list[dict], equity_curve: list[dict]}
        """
        symbol = config["symbol"]
        timeframe = config["timeframe"]
        balance = config["initial_balance"]
        default_spread_price = config.get("spread_pips", 1.5) * _pip_value(symbol)
        mode = config.get("execution_mode", "close_price")
        volume = config.get("volume", 0.1)
        risk_pct = config.get("risk_pct") or 0.0   # 0 = use fixed volume; >0 = risk-based sizing
        max_llm = config.get("max_llm_calls", 100)
        total = len(candles)

        # LLM sampling step: call LLM every K-th candle
        is_llm_strategy = getattr(strategy, "strategy_type", "code") in ("config", "prompt")
        llm_step = max(1, total // max_llm) if is_llm_strategy and max_llm > 0 else None

        open_position: dict | None = None  # one position at a time
        trades: list[dict] = []
        equity_curve: list[dict] = []
        last_signal: dict | None = None

        # Pointer-based context TF windows: advance each pointer as primary TF time moves
        # forward. O(n + m) total vs O(n×m) for naive filtering per candle.
        ctx_ptrs: dict[str, int] = {tf: 0 for tf in (context_candles or {})}

        for i, candle in enumerate(candles):
            # Advance context TF pointers to include all candles with time <= current
            if context_candles:
                candle_time = candle["time"]
                for ctx_tf, ctx_list in context_candles.items():
                    while (ctx_ptrs[ctx_tf] < len(ctx_list)
                           and ctx_list[ctx_ptrs[ctx_tf]]["time"] <= candle_time):
                        ctx_ptrs[ctx_tf] += 1
            # Per-candle spread (from CSV); falls back to config spread_pips
            spread_pts = candle.get("spread", 0)
            candle_spread_price = (
                _spread_to_price(spread_pts, symbol) if spread_pts > 0
                else default_spread_price
            )

            # ── 1. Check open position SL/TP ──────────────────────────────────
            if open_position is not None:
                closed = _check_exit(open_position, candle, mode)
                if closed:
                    profit = _calc_profit(open_position, closed["exit_price"], open_position["volume"], symbol)
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
                        from strategies.base_strategy import AbstractStrategy as _AbstractStrategy
                        if isinstance(strategy, _AbstractStrategy):
                            # New AbstractStrategy — build MTFMarketData and await run()
                            from services.mtf_data import MTFMarketData, TimeframeData
                            _candle_counts = getattr(strategy, "candle_counts", {})
                            _timeframes = {
                                timeframe: TimeframeData(tf=timeframe, candles=[
                                    _dict_to_ohlcv(c) for c in window
                                ])
                            }
                            # Add context TF windows (no-lookahead: ptr = index of first
                            # candle AFTER current primary TF time, so slice [:ptr])
                            if context_candles:
                                for ctx_tf, ctx_list in context_candles.items():
                                    if ctx_tf == timeframe:
                                        continue  # same as primary — don't overwrite
                                    ptr = ctx_ptrs[ctx_tf]
                                    if ptr == 0:
                                        continue
                                    ctx_count = _candle_counts.get(ctx_tf, 20)
                                    ctx_win = ctx_list[max(0, ptr - ctx_count): ptr]
                                    _timeframes[ctx_tf] = TimeframeData(
                                        tf=ctx_tf,
                                        candles=[_dict_to_ohlcv(c) for c in ctx_win],
                                    )
                            mtf_md = MTFMarketData(
                                symbol=symbol,
                                primary_tf=timeframe,
                                current_price=candle["close"],
                                timeframes=_timeframes,
                                indicators=_build_indicators(window),
                                trigger_time=candle["time"],
                            )
                            strategy_result = await strategy.run(mtf_md)
                            signal = _strategy_result_to_dict(strategy_result)
                        else:
                            signal = strategy.generate_signal(market_data)
                    except Exception as exc:
                        logger.warning("signal generation error at candle %d: %s", i, exc)
                        signal = None
                    last_signal = signal

                # ── 3. Open new position ───────────────────────────────────────
                if signal and signal.get("action") in ("BUY", "SELL"):
                    fill_price = _fill_price(signal, candle, candles, i, mode, candle_spread_price)
                    if fill_price is not None:
                        # Guard 1: SL/TP must bracket the fill price on the correct sides.
                        # Skips signals where strategy entry (D point) diverged too far
                        # from the actual fill (candle close), flipping SL/TP sides.
                        _sl = signal.get("stop_loss", 0)
                        _tp = signal.get("take_profit", 0)
                        _dir = signal["action"]
                        _valid = (
                            (_dir == "BUY" and _sl < fill_price < _tp) or
                            (_dir == "SELL" and _tp < fill_price < _sl)
                        )
                        if not _valid:
                            logger.debug(
                                "Skipping %s at %s: fill=%.5f outside sl=%.5f/tp=%.5f",
                                _dir, candle["time"], fill_price, _sl, _tp,
                            )
                            fill_price = None

                    if fill_price is not None:
                        # Guard 2: Minimum SL distance (0.1 % of fill price).
                        # Filters out degenerate harmonic patterns with microscopic legs
                        # that would otherwise produce unrealistic lot sizes or near-zero P&L.
                        _min_sl_dist = fill_price * 0.001
                        _sl_dist = abs(fill_price - _sl)
                        if _sl_dist < _min_sl_dist:
                            logger.debug(
                                "Skipping %s at %s: SL too close (dist=%.5f < min=%.5f)",
                                signal["action"], candle["time"], _sl_dist, _min_sl_dist,
                            )
                            fill_price = None

                    if fill_price is not None:
                        # Lot sizing: risk-based (if risk_pct > 0) or fixed volume.
                        if risk_pct > 0:
                            from services.position_sizing import calc_lot_size
                            trade_volume = calc_lot_size(
                                balance=balance,
                                risk_pct=risk_pct,
                                fill_price=fill_price,
                                sl_price=_sl,
                                contract_size=_contract_size(symbol),
                            )
                        else:
                            trade_volume = volume

                        open_position = {
                            "symbol": symbol,
                            "direction": signal["action"],
                            "entry_time": candle["time"],
                            "entry_price": round(fill_price, 5),
                            "stop_loss": round(signal["stop_loss"], 5),
                            "take_profit": round(signal["take_profit"], 5),
                            "volume": trade_volume,
                            "exit_time": None,
                            "exit_price": None,
                            "exit_reason": None,
                            "profit": None,
                            "equity_after": None,
                            "pattern_name": signal.get("pattern_name"),
                            "pattern_metadata": signal.get("pattern_metadata"),
                        }

            # ── 4. Progress callback ───────────────────────────────────────────
            if progress_cb and i % 1000 == 0 and i > 0:
                pct = int(i / total * 100)
                await progress_cb(pct)

        # ── Close any open position at end of data ─────────────────────────────
        if open_position is not None:
            last_candle = candles[-1]
            profit = _calc_profit(open_position, last_candle["close"], open_position["volume"], symbol)
            balance += profit
            trade = {
                **open_position,
                "exit_time": last_candle["time"],
                "exit_price": round(last_candle["close"], 5),
                "exit_reason": "end_of_data",
                "profit": round(profit, 4),
                "equity_after": round(balance, 4),
                "pattern_name": open_position.get("pattern_name"),
                "pattern_metadata": open_position.get("pattern_metadata"),
            }
            trades.append(trade)
            equity_curve.append({"time": last_candle["time"], "equity": round(balance, 4)})

        non_zero_spreads = [c.get("spread", 0) for c in candles if c.get("spread", 0) > 0]
        avg_spread: float | None = (
            round(sum(non_zero_spreads) / len(non_zero_spreads), 1)
            if non_zero_spreads else None
        )

        logger.info(
            "Backtest complete | %d candles | %d trades | final_equity=%.2f",
            total, len(trades), balance,
        )
        return {"trades": trades, "equity_curve": equity_curve, "avg_spread": avg_spread}


# ── Private helpers ────────────────────────────────────────────────────────────

def _pip_value(symbol: str) -> float:
    """Convert 1 pip to price units. JPY pairs use 0.01, others 0.0001."""
    return 0.01 if "JPY" in symbol else 0.0001


def _spread_to_price(spread_pts: int, symbol: str) -> float:
    """Convert MT5 spread in points to a price offset.

    MT5 point size by instrument:
      JPY pairs   : 1 pt = 0.001
      Metals/index: 1 pt = 0.01  (XAU, XAG, US30, NAS, SPX, DAX)
      Forex 5-digit: 1 pt = 0.00001  (default)
    """
    if "JPY" in symbol:
        return spread_pts * 0.001
    if any(m in symbol for m in ("XAU", "XAG", "US30", "NAS", "SPX", "DAX")):
        return spread_pts * 0.01
    return spread_pts * 0.00001


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


def _contract_size(symbol: str) -> float:
    """Return standard lot contract size for a symbol.

    XAUUSD/XAGUSD: 100 oz per lot (not 100,000 — gold is priced per oz)
    Indices (US30, NAS, SPX, DAX, FTSE, CAC): 1 unit per lot
    Crude oil (OIL, BRENT, WTI): 1,000 barrels per lot
    Forex (all others): 100,000 units per lot
    """
    sym = symbol.upper()
    if any(m in sym for m in ("XAU", "XAG")):
        return 100        # Gold/Silver: 100 troy oz per standard lot
    if any(m in sym for m in ("XPT", "XPD")):
        return 50         # Platinum/Palladium: 50 oz
    if any(m in sym for m in ("US30", "NAS", "SPX", "DAX", "FTSE", "CAC", "NDX", "UK100", "JP225")):
        return 1          # Index CFDs: 1 unit (broker-dependent, 1 is safest default)
    if any(m in sym for m in ("OIL", "BRENT", "WTI", "USOIL", "UKOIL")):
        return 1_000      # Crude oil: 1,000 barrels per standard lot
    return 100_000        # Standard forex: 100,000 units per lot


def _calc_profit(pos: dict, exit_price: float, volume: float, symbol: str) -> float:
    """Calculate P&L in account currency."""
    entry = pos["entry_price"]
    direction_sign = 1 if pos["direction"] == "BUY" else -1
    price_diff = (exit_price - entry) * direction_sign
    return price_diff * volume * _contract_size(symbol)


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
