"""Pure helper functions used by BacktestEngine: conversion, indicator, and fill/exit math."""
from __future__ import annotations

from services.backtest_engine._models import OpenPosition
from services.instrument_spec import contract_size


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
        "take_profit_levels": result.take_profit_levels,
        "confidence": result.confidence,
        "rationale": result.rationale,
        "timeframe": result.timeframe,
        "pattern_name": result.pattern_name,
        "pattern_metadata": result.pattern_metadata,
    }


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


def _check_exit(pos: OpenPosition, candle: dict, mode: str, tp_partial_close_ratio: float = 0.5, spread: float = 0.0) -> tuple[dict | None, dict | None]:
    """Return (fully_closed_info, partial_closed_info) tuples."""
    direction = pos.direction
    sl = pos.stop_loss
    tp = pos.take_profit
    tp_levels = pos.take_profit_levels
    tp_idx = pos.tp_level_idx

    # We dynamically switch intended TP to the active TP level
    active_tp = tp
    if tp_levels and tp_idx < len(tp_levels):
        active_tp = tp_levels[tp_idx]

    # SL fills slightly beyond the SL level to simulate gap/slippage
    sl_fill = sl - spread if direction == "BUY" else sl + spread

    t = candle["time"]

    fully_closed = None
    partial_closed = None

    if mode == "close_price":
        price = candle["close"]
        if direction == "BUY":
            if price <= sl:
                fully_closed = {"exit_time": t, "exit_price": sl_fill, "exit_reason": "sl"}
            elif price >= active_tp:
                if tp_levels and tp_idx < len(tp_levels) - 1:
                    # Partial TP reached
                    partial_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": f"tp{tp_idx+1}", "volume_closed": pos.volume * tp_partial_close_ratio, "new_sl": pos.entry_price}
                    pos.tp_level_idx = tp_idx + 1
                else:
                    fully_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": "tp"}
        else:  # SELL
            if price >= sl:
                fully_closed = {"exit_time": t, "exit_price": sl_fill, "exit_reason": "sl"}
            elif price <= active_tp:
                if tp_levels and tp_idx < len(tp_levels) - 1:
                    # Partial TP reached
                    partial_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": f"tp{tp_idx+1}", "volume_closed": pos.volume * tp_partial_close_ratio, "new_sl": pos.entry_price}
                    pos.tp_level_idx = tp_idx + 1
                else:
                    fully_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": "tp"}
    else:  # intra_candle
        high, low = candle["high"], candle["low"]
        open_p = candle["open"]
        if direction == "BUY":
            sl_hit = low <= sl
            tp_hit = high >= active_tp
            if sl_hit and tp_hit:
                if abs(open_p - sl) <= abs(open_p - active_tp):
                    fully_closed = {"exit_time": t, "exit_price": sl_fill, "exit_reason": "sl"}
                else:
                    if tp_levels and tp_idx < len(tp_levels) - 1:
                        partial_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": f"tp{tp_idx+1}", "volume_closed": pos.volume * tp_partial_close_ratio, "new_sl": pos.entry_price}
                        pos.tp_level_idx = tp_idx + 1
                        # Note: we might theoretically hit the new SL inside the same candle, but for simplicity we ignore this micro-action.
                    else:
                        fully_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": "tp"}
            elif sl_hit:
                fully_closed = {"exit_time": t, "exit_price": sl_fill, "exit_reason": "sl"}
            elif tp_hit:
                if tp_levels and tp_idx < len(tp_levels) - 1:
                    partial_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": f"tp{tp_idx+1}", "volume_closed": pos.volume * tp_partial_close_ratio, "new_sl": pos.entry_price}
                    pos.tp_level_idx = tp_idx + 1
                else:
                    fully_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": "tp"}
        else:  # SELL
            sl_hit = high >= sl
            tp_hit = low <= active_tp
            if sl_hit and tp_hit:
                if abs(open_p - sl) <= abs(open_p - active_tp):
                    fully_closed = {"exit_time": t, "exit_price": sl_fill, "exit_reason": "sl"}
                else:
                    if tp_levels and tp_idx < len(tp_levels) - 1:
                        partial_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": f"tp{tp_idx+1}", "volume_closed": pos.volume * tp_partial_close_ratio, "new_sl": pos.entry_price}
                        pos.tp_level_idx = tp_idx + 1
                    else:
                        fully_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": "tp"}
            elif sl_hit:
                fully_closed = {"exit_time": t, "exit_price": sl_fill, "exit_reason": "sl"}
            elif tp_hit:
                if tp_levels and tp_idx < len(tp_levels) - 1:
                    partial_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": f"tp{tp_idx+1}", "volume_closed": pos.volume * tp_partial_close_ratio, "new_sl": pos.entry_price}
                    pos.tp_level_idx = tp_idx + 1
                else:
                    fully_closed = {"exit_time": t, "exit_price": active_tp, "exit_reason": "tp"}

    return fully_closed, partial_closed


def _fill_price(
    signal: dict, candles: list, i: int, spread: float
) -> float | None:
    """Determine fill price based on execution mode and order type."""
    action = signal["action"]

    # Perfect fill simulation for pending orders
    # Note: A real backtester would verify the candle touches the limit price.
    # For speed and simplicity in harmonic pattern backtesting, we assume it gets hit
    # if the pattern is flagged as triggered.
    if action in {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}:
        return signal.get("entry")

    # intra_candle / close_price: fill at next open + spread (no lookahead)
    if i + 1 < len(candles):
        next_open = candles[i + 1]["open"]
        return next_open + spread if action == "BUY" else next_open - spread
    return None  # no next candle, skip


def _calc_profit(pos: OpenPosition, exit_price: float, volume: float, symbol: str) -> float:
    """Calculate P&L in account currency."""
    direction_sign = 1 if pos.direction == "BUY" else -1
    price_diff = (exit_price - pos.entry_price) * direction_sign
    return price_diff * volume * contract_size(symbol)


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
