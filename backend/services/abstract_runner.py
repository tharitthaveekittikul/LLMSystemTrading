"""Runner for AbstractStrategy subclasses.

Executes strategies that implement the new `run(MTFMarketData)` interface.
Runs within a PipelineTracer context to log execution steps to the DB.
"""
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.models import Account, AIJournal
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import MT5Executor, OrderRequest, pending_expiry_hours
from services.ai_trading import _TIMEFRAME_MAP, StrategyOverrides, _calculate_lot_size
from services.kill_switch import is_active as kill_switch_active
from services.mtf_data import OHLCV, MTFMarketData, TimeframeData
from services.pipeline_tracer import PipelineTracer
from strategies.base_strategy import AbstractStrategy, StrategyResult

logger = logging.getLogger(__name__)


async def fetch_strategy_signal(
    symbol: str,
    timeframe: str,
    strategy_instance: AbstractStrategy,
    primary_account: "Account",
) -> "tuple[StrategyResult | None, MTFMarketData | None, str]":
    """Phase 1 for AbstractStrategy group job: fetch MTF data and run strategy once.

    Returns (signal, market_data, mt5_symbol). Uses primary_account credentials.
    """
    password = decrypt(primary_account.password_encrypted)
    creds = AccountCredentials(
        login=primary_account.login, password=password,
        server=primary_account.server,
        path=primary_account.mt5_path or settings.mt5_path,
    )

    timeframes_to_fetch = set([strategy_instance.primary_tf] + list(strategy_instance.context_tfs))
    mtf_timeframes: dict[str, TimeframeData] = {}
    mt5_symbol = symbol
    current_price: float | None = None
    trigger_time = None

    try:
        async with MT5Bridge(creds) as bridge:
            mt5_symbol = await bridge.get_broker_symbol(symbol)
            tick = await bridge.get_tick(mt5_symbol)
            if tick:
                current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

            for tf_str in timeframes_to_fetch:
                tf_int = _TIMEFRAME_MAP.get(tf_str)
                if tf_int is None:
                    continue
                count = strategy_instance.candle_counts.get(tf_str, 20)
                candles_raw = await bridge.get_rates(mt5_symbol, tf_int, count + 10)
                if not candles_raw:
                    continue
                ohlcv_list = [
                    OHLCV(time=c["time"], open=c["open"], high=c["high"],
                          low=c["low"], close=c["close"],
                          tick_volume=c.get("tick_volume", 0), spread=c.get("spread", 0))
                    for c in candles_raw
                ]
                ohlcv_list = ohlcv_list[-count:] if len(ohlcv_list) > count else ohlcv_list
                mtf_timeframes[tf_str] = TimeframeData(tf=tf_str, candles=ohlcv_list)
                if tf_str == strategy_instance.primary_tf and ohlcv_list:
                    trigger_time = ohlcv_list[-1].time
                    if current_price is None:
                        current_price = ohlcv_list[-1].close
    except Exception as exc:
        logger.exception("fetch_strategy_signal: data fetch failed | symbol=%s: %s", symbol, exc)
        return None, None, mt5_symbol

    if strategy_instance.primary_tf not in mtf_timeframes or not trigger_time:
        logger.error("fetch_strategy_signal: primary TF data missing | symbol=%s", symbol)
        return None, None, mt5_symbol

    market_data = MTFMarketData(
        symbol=symbol, primary_tf=strategy_instance.primary_tf,
        current_price=current_price or 0,
        timeframes=mtf_timeframes, indicators={}, trigger_time=trigger_time,
    )

    try:
        signal = await strategy_instance.run(market_data)
    except Exception:
        logger.exception("fetch_strategy_signal: strategy.run() failed | symbol=%s", symbol)
        return None, market_data, mt5_symbol

    return signal, market_data, mt5_symbol


async def execute_abstract_for_account(
    account_id: int,
    symbol: str,
    timeframe: str,
    signal: "StrategyResult",
    mt5_symbol: str,
    strategy_id: "int | None",
    strategy_overrides: "StrategyOverrides | None",
    db: "AsyncSession",
) -> "tuple[StrategyResult | None, int | None]":
    """Phase 2 for AbstractStrategy group job: per-account journal, WS broadcast, and MT5 order."""
    async with PipelineTracer(account_id, symbol, timeframe, strategy_id=strategy_id) as tracer:
        t0 = time.monotonic()
        account: Account | None = await db.get(Account, account_id)
        if not account or not account.is_active:
            await tracer.record("account_loaded", status="error",
                                error="Account not found or inactive",
                                duration_ms=int((time.monotonic() - t0) * 1000))
            tracer.finalize(status="failed")
            return None, None

        await tracer.record("account_loaded",
                            output_data={"name": account.name,
                                         "auto_trade_enabled": account.auto_trade_enabled},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        # Kill switch
        if kill_switch_active():
            tracer.finalize(status="failed")
            return None, None

        # Persist AIJournal
        journal = AIJournal(
            account_id=account_id, trade_id=None, symbol=symbol, timeframe=timeframe,
            signal=signal.action, confidence=signal.confidence, rationale=signal.rationale,
            indicators_snapshot="{}", llm_provider="group_rule",
            model_name="AbstractStrategy",
            strategy_id=strategy_id,
        )
        db.add(journal)
        await db.commit()
        await db.refresh(journal)
        await tracer.record("journal_saved", output_data={"journal_id": journal.id})

        # Broadcast
        from api.routes.ws import broadcast as _broadcast
        await _broadcast(account_id, "ai_signal", {
            "journal_id": journal.id, "symbol": symbol, "timeframe": timeframe,
            "action": signal.action, "confidence": signal.confidence,
            "rationale": signal.rationale, "entry": signal.entry,
            "stop_loss": signal.stop_loss, "take_profit": signal.take_profit,
        })

        if signal.action == "HOLD":
            tracer.finalize(status="hold", final_action="HOLD", journal_id=journal.id)
            return signal, journal.id

        if kill_switch_active() or not account.auto_trade_enabled:
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return signal, journal.id

        # Lot sizing
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login, password=password,
            server=account.server, path=account.mt5_path or settings.mt5_path,
        )

        if strategy_overrides and strategy_overrides.lot_size is not None:
            effective_lot = strategy_overrides.lot_size
        else:
            effective_lot = account.max_lot_size
            try:
                async with MT5Bridge(creds) as lot_bridge:
                    acct_info = await lot_bridge.get_account_info()
                    sym_info = await lot_bridge.get_symbol_info(mt5_symbol)
                if acct_info and sym_info:
                    balance = float(acct_info.get("balance", 0))
                    tick_value = float(sym_info.get("trade_tick_value", 0))
                    tick_size = float(sym_info.get("trade_tick_size", 0))
                    pip_size = tick_size * 10 if tick_size > 0 else 0.0001
                    sl_distance = abs((signal.entry or 0) - (signal.stop_loss or 0))
                    sl_pips = sl_distance / pip_size if pip_size > 0 else 0
                    effective_lot = _calculate_lot_size(
                        balance=balance, risk_pct=account.risk_pct,
                        sl_pips=sl_pips, pip_value_per_lot=tick_value,
                        max_lot=account.max_lot_size,
                    )
            except Exception as exc:
                logger.warning("Dynamic lot sizing failed in abstract group execution | account_id=%s: %s",
                               account_id, exc)

        order_req = OrderRequest(
            symbol=mt5_symbol, action=signal.action, volume=effective_lot,
            entry_price=signal.entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            comment="AI-Trade-Group", expiration_hours=pending_expiry_hours(timeframe),
        )

        executor = MT5Executor(creds)
        t0 = time.monotonic()
        try:
            exec_result = await executor.execute(order_req)
        except Exception:
            logger.exception("MT5 execution failed in abstract group job | account_id=%s", account_id)
            tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
            return signal, journal.id

        await tracer.record("mt5_execution",
                            output_data={"success": exec_result.success, "ticket": exec_result.ticket},
                            duration_ms=int((time.monotonic() - t0) * 1000))

        if not exec_result.success:
            tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
            return signal, journal.id

        journal.trade_id = exec_result.ticket
        await db.commit()
        tracer.finalize(status="completed", final_action=signal.action,
                        journal_id=journal.id, trade_id=exec_result.ticket)
        return signal, journal.id
