"""BacktestEngine — runs a strategy against historical candles and produces trades + equity curve."""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Awaitable, Callable

from services.backtest_engine._helpers import (
    _build_indicators,
    _build_market_data,
    _calc_profit,
    _check_exit,
    _dict_to_ohlcv,
    _fill_price,
    _pip_value,
    _spread_to_price,
    _strategy_result_to_dict,
)
from services.backtest_engine._models import OpenPosition, TradeResult
from services.instrument_spec import contract_size

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
        commission_per_lot: float = config.get("commission_per_lot", 0.0)
        tp_partial_close_ratio: float = config.get("tp_partial_close_ratio", 0.5)
        total = len(candles)

        # Source label for recorded trades — strategy class name (e.g. "HarmonicStrategy")
        trade_source: str = type(strategy).__name__

        # LLM sampling step: call LLM every K-th candle
        is_llm_strategy = getattr(strategy, "strategy_type", "code") in ("config", "prompt")
        llm_step = max(1, total // max_llm) if is_llm_strategy and max_llm > 0 else None

        # skip_llm: activate rule-only fallback for RuleThenLLMStrategy (no API cost)
        if config.get("skip_llm") and hasattr(strategy, "_skip_llm"):
            strategy._skip_llm = True

        open_position: OpenPosition | None = None  # one position at a time
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
                closed, partial_profit_event = _check_exit(open_position, candle, mode, tp_partial_close_ratio, candle_spread_price)

                if partial_profit_event:
                    # Scale out: close a portion of the trade and adjust SL
                    vol_closed = partial_profit_event["volume_closed"]
                    profit = _calc_profit(open_position, partial_profit_event["exit_price"], vol_closed, symbol)
                    commission = commission_per_lot * vol_closed
                    profit -= commission
                    balance += profit

                    trades.append(asdict(TradeResult(
                        symbol=open_position.symbol,
                        direction=open_position.direction,
                        entry_time=open_position.entry_time,
                        entry_price=open_position.entry_price,
                        stop_loss=open_position.stop_loss,
                        take_profit=open_position.take_profit,
                        volume=vol_closed,
                        exit_time=partial_profit_event["exit_time"],
                        exit_price=partial_profit_event["exit_price"],
                        exit_reason=partial_profit_event["exit_reason"],
                        profit=round(profit, 4),
                        equity_after=round(balance, 4),
                        pattern_name=open_position.pattern_name,
                        pattern_metadata=open_position.pattern_metadata,
                        source=trade_source,
                    )))
                    equity_curve.append({"time": partial_profit_event["exit_time"], "equity": round(balance, 4)})

                    open_position.volume -= vol_closed
                    # If we don't have enough volume to keep going, we fully close it
                    if open_position.volume < 0.001:
                        open_position = None
                    else:
                        open_position.stop_loss = partial_profit_event["new_sl"]

                if closed and open_position is not None:
                    # Fully closed
                    vol_closed = open_position.volume
                    profit = _calc_profit(open_position, closed["exit_price"], vol_closed, symbol)
                    commission = commission_per_lot * vol_closed
                    profit -= commission
                    balance += profit
                    trades.append(asdict(TradeResult(
                        symbol=open_position.symbol,
                        direction=open_position.direction,
                        entry_time=open_position.entry_time,
                        entry_price=open_position.entry_price,
                        stop_loss=open_position.stop_loss,
                        take_profit=open_position.take_profit,
                        volume=vol_closed,
                        exit_time=closed["exit_time"],
                        exit_price=closed["exit_price"],
                        exit_reason=closed["exit_reason"],
                        profit=round(profit, 4),
                        equity_after=round(balance, 4),
                        pattern_name=open_position.pattern_name,
                        pattern_metadata=open_position.pattern_metadata,
                        source=trade_source,
                    )))
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
                if signal and signal.get("action") in ("BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
                    # Resolve underlying direction (BUY/SELL)
                    from strategies.base_strategy import direction_from_action
                    actual_dir = direction_from_action(signal.get("action"))

                    fill_price = _fill_price(signal, candles, i, candle_spread_price)
                    if fill_price is not None:
                        # Guard 1: SL/TP must bracket the fill price on the correct sides.
                        # Skips signals where strategy entry (D point) diverged too far
                        # from the actual fill (candle close), flipping SL/TP sides.
                        _sl = signal.get("stop_loss", 0)
                        _tp = signal.get("take_profit", 0)
                        _valid = (
                            (actual_dir == "BUY" and _sl < fill_price < _tp) or
                            (actual_dir == "SELL" and _tp < fill_price < _sl)
                        )
                        if not _valid:
                            logger.debug(
                                "Skipping %s at %s: fill=%.5f outside sl=%.5f/tp=%.5f",
                                signal["action"], candle["time"], fill_price, _sl, _tp,
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
                                contract_size=contract_size(symbol),
                            )
                        else:
                            trade_volume = volume

                        open_position = OpenPosition(
                            symbol=symbol,
                            direction=actual_dir,
                            entry_time=candle["time"],
                            entry_price=round(fill_price, 5),
                            stop_loss=round(signal["stop_loss"], 5),
                            take_profit=round(signal["take_profit"], 5),
                            take_profit_levels=signal.get("take_profit_levels"),
                            tp_level_idx=0,
                            volume=trade_volume,
                            pattern_name=signal.get("pattern_name"),
                            pattern_metadata=signal.get("pattern_metadata"),
                        )

            # ── 4. Progress callback ───────────────────────────────────────────
            if progress_cb and i % 1000 == 0 and i > 0:
                pct = int(i / total * 100)
                await progress_cb(pct)

        # ── Close any open position at end of data ─────────────────────────────
        if open_position is not None:
            last_candle = candles[-1]
            profit = _calc_profit(open_position, last_candle["close"], open_position.volume, symbol)
            profit -= commission_per_lot * open_position.volume
            balance += profit
            trades.append(asdict(TradeResult(
                symbol=open_position.symbol,
                direction=open_position.direction,
                entry_time=open_position.entry_time,
                entry_price=open_position.entry_price,
                stop_loss=open_position.stop_loss,
                take_profit=open_position.take_profit,
                volume=open_position.volume,
                exit_time=last_candle["time"],
                exit_price=round(last_candle["close"], 5),
                exit_reason="end_of_data",
                profit=round(profit, 4),
                equity_after=round(balance, 4),
                pattern_name=open_position.pattern_name,
                pattern_metadata=open_position.pattern_metadata,
                source=trade_source,
            )))
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

