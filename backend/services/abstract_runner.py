"""Runner for AbstractStrategy subclasses.

Executes strategies that implement the new `run(MTFMarketData)` interface.
Runs within a PipelineTracer context to log execution steps to the DB.
"""
import logging
import time

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.models import Account, AIJournal
from db.redis import get_candle_cache, set_candle_cache
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import MT5Executor, OrderRequest
from services.ai_trading import _calculate_lot_size, _CACHE_TTL, _TIMEFRAME_MAP, StrategyOverrides
from services.kill_switch import is_active as kill_switch_active
from services.mtf_data import MTFMarketData, TimeframeData, OHLCV
from services.pipeline_tracer import PipelineTracer
from strategies.base_strategy import StrategyResult, AbstractStrategy

logger = logging.getLogger(__name__)


async def run_abstract_strategy_pipeline(
    account_id: int,
    symbol: str,
    timeframe: str,  # Primary timeframe passed from scheduler
    db: AsyncSession,
    strategy_id: int | None,
    strategy_overrides: StrategyOverrides | None,
    strategy_instance: AbstractStrategy,
) -> tuple[StrategyResult | None, int | None]:
    """Execute an AbstractStrategy within a PipelineTracer context."""
    async with PipelineTracer(account_id, symbol, timeframe, strategy_id=strategy_id) as tracer:
        return await _run_pipeline(
            tracer, account_id, symbol, timeframe, db, strategy_id, strategy_overrides, strategy_instance
        )


async def _run_pipeline(
    tracer: PipelineTracer,
    account_id: int,
    symbol: str,
    timeframe: str,
    db: AsyncSession,
    strategy_id: int | None,
    strategy_overrides: StrategyOverrides | None,
    strategy_instance: AbstractStrategy,
) -> tuple[StrategyResult | None, int | None]:
    """Internal runner logic with traced steps."""
    
    # ── 1. Load account ──────────────────────────────────────────────────
    t0 = time.monotonic()
    account: Account | None = await db.get(Account, account_id)
    if not account or not account.is_active:
        await tracer.record(
            "account_loaded", status="error",
            error="Account not found or inactive",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="failed")
        return None, None
        
    await tracer.record(
        "account_loaded",
        output_data={
            "name": account.name,
            "auto_trade_enabled": account.auto_trade_enabled,
            "max_lot_size": account.max_lot_size,
        },
        duration_ms=int((time.monotonic() - t0) * 1000),
    )

    # ── 2. Kill switch check ──────────────────────────────────────────────
    t0 = time.monotonic()
    ks_early = kill_switch_active()
    await tracer.record(
        "kill_switch_check",
        output_data={"active": ks_early},
        duration_ms=int((time.monotonic() - t0) * 1000),
    )
    if ks_early:
        logger.warning(
            "Kill switch active — aborting pipeline before analysis | account_id=%s symbol=%s",
            account_id, symbol,
        )
        tracer.finalize(status="failed")
        return None, None

    # ── 3. Fetch Data for Required Timeframes ─────────────────────────────
    t0 = time.monotonic()
    
    password = decrypt(account.password_encrypted)
    creds = AccountCredentials(
        login=account.login, password=password,
        server=account.server, path=account.mt5_path or settings.mt5_path,
    )

    timeframes_to_fetch = set([strategy_instance.primary_tf] + list(strategy_instance.context_tfs))
    
    mtf_timeframes: dict[str, TimeframeData] = {}
    mt5_symbol = symbol
    current_price: float | None = None
    trigger_time = None
    ohlcv_source = "cache_or_mt5"

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
                # Ensure we fetch enough candles (add buffer)
                candles_raw = await bridge.get_rates(mt5_symbol, tf_int, count + 10)
                
                if not candles_raw:
                    continue
                    
                ohlcv_list = []
                for c in candles_raw:
                    ohlcv_list.append(OHLCV(
                        time=c["time"],
                        open=c["open"],
                        high=c["high"],
                        low=c["low"],
                        close=c["close"],
                        tick_volume=c.get("tick_volume", 0),
                        spread=c.get("spread", 0)
                    ))
                
                # Keep exactly the number requested
                ohlcv_list = ohlcv_list[-count:] if len(ohlcv_list) > count else ohlcv_list
                mtf_timeframes[tf_str] = TimeframeData(tf=tf_str, candles=ohlcv_list)
                
                # Use primary_tf for trigger time
                if tf_str == strategy_instance.primary_tf and ohlcv_list:
                    trigger_time = ohlcv_list[-1].time
                    if current_price is None:
                        current_price = ohlcv_list[-1].close
                        
    except Exception as exc:
        await tracer.record(
            "ohlcv_fetch", status="error",
            input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframes": list(timeframes_to_fetch)},
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="failed")
        return None, None

    if strategy_instance.primary_tf not in mtf_timeframes or not trigger_time:
         await tracer.record(
            "ohlcv_fetch", status="error",
            input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframes": list(timeframes_to_fetch)},
            error="Failed to fetch primary timeframe data",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
         tracer.finalize(status="failed")
         return None, None
         
    # Build MTFMarketData
    market_data = MTFMarketData(
        symbol=symbol,
        primary_tf=strategy_instance.primary_tf,
        current_price=current_price or 0,
        timeframes=mtf_timeframes,
        indicators={},  # Not computing default indicators for new strategy type right now
        trigger_time=trigger_time,
    )
    
    await tracer.record(
        "ohlcv_fetch",
        input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframes": list(timeframes_to_fetch)},
        output_data={
            "source": ohlcv_source,
            "fetched_tfs": list(mtf_timeframes.keys()),
            "current_price": current_price,
            "trigger_time": str(trigger_time),
        },
        duration_ms=int((time.monotonic() - t0) * 1000),
    )

    # ── 4. Execute Strategy ───────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        signal = await strategy_instance.run(market_data)
    except Exception as exc:
        logger.exception("Strategy execution failed | symbol=%s strategy=%s", symbol, type(strategy_instance).__name__)
        await tracer.record(
            "strategy_execution", status="error",
            input_data={"strategy": type(strategy_instance).__name__},
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="failed")
        return None, None
        
    await tracer.record(
        "strategy_execution",
        output_data={
            "strategy": type(strategy_instance).__name__,
            "action": signal.action,
            "confidence": signal.confidence,
            "rationale": signal.rationale[:200],
            "pattern_name": getattr(signal, "pattern_name", None),
        },
        duration_ms=int((time.monotonic() - t0) * 1000),
    )

    # ── 5. Persist AIJournal ──────────────────────────────────────────────
    t0 = time.monotonic()
    journal = AIJournal(
        account_id=account_id,
        trade_id=None,
        symbol=symbol,
        timeframe=timeframe,
        signal=signal.action,
        confidence=signal.confidence,
        rationale=signal.rationale,
        indicators_snapshot="{}",
        llm_provider=strategy_instance.execution_mode,
        model_name=type(strategy_instance).__name__,
        strategy_id=strategy_id,
        pattern_name=getattr(signal, "pattern_name", None),
        pattern_metadata=getattr(signal, "pattern_metadata", None),
    )
    db.add(journal)
    await db.commit()
    await db.refresh(journal)
    await tracer.record(
        "journal_saved",
        output_data={"journal_id": journal.id},
        duration_ms=int((time.monotonic() - t0) * 1000),
    )

    # ── 6. Broadcast ai_signal ────────────────────────────────────────────
    from api.routes.ws import broadcast
    await broadcast(account_id, "ai_signal", {
        "journal_id": journal.id,
        "symbol": symbol,
        "timeframe": timeframe,
        "action": signal.action,
        "confidence": signal.confidence,
        "rationale": signal.rationale,
        "entry": signal.entry,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
    })

    # ── 7. Check if HOLD or Skip ──────────────────────────────────────────
    if signal.action == "HOLD":
        await tracer.record(
            "kill_switch_check",
            output_data={"active": False, "skipped": "HOLD signal"},
        )
        logger.info("Signal HOLD — no order | account_id=%s symbol=%s", account_id, symbol)
        tracer.finalize(status="hold", final_action="HOLD", journal_id=journal.id)
        return signal, journal.id

    ks_active = kill_switch_active()
    await tracer.record("kill_switch_check", output_data={"active": ks_active})
    if ks_active:
        logger.warning(
            "Kill switch active — signal saved but order skipped | account_id=%s symbol=%s",
            account_id, symbol,
        )
        tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
        return signal, journal.id

    if not account.auto_trade_enabled:
        logger.info(
            "Auto-trade disabled — signal saved but order skipped | account_id=%s",
            account_id,
        )
        tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
        return signal, journal.id

    # ── 8. Calculate dynamic lot size & Create Order ──────────────────────
    t0 = time.monotonic()
    sl_pips: float | None = None
    pip_value_per_lot: float | None = None
    balance: float | None = None
    
    if strategy_overrides and strategy_overrides.lot_size is not None:
        effective_lot_size = strategy_overrides.lot_size
    else:
        effective_lot_size = account.max_lot_size
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
                pip_value_per_lot = tick_value
                effective_lot_size = _calculate_lot_size(
                    balance=balance,
                    risk_pct=account.risk_pct,
                    sl_pips=sl_pips,
                    pip_value_per_lot=pip_value_per_lot,
                    max_lot=account.max_lot_size,
                )
        except Exception as exc:
            logger.warning(
                "Dynamic lot size failed — using max_lot_size fallback | account_id=%s | %s",
                account_id, exc,
            )
            
    await tracer.record(
        "lot_size_calculated",
        output_data={
            "effective_lot_size": effective_lot_size,
            "max_lot_size": account.max_lot_size,
            "risk_pct": account.risk_pct,
            "sl_pips": sl_pips,
            "pip_value_per_lot": pip_value_per_lot,
            "balance": balance,
        },
        duration_ms=int((time.monotonic() - t0) * 1000),
    )

    t0 = time.monotonic()
    order_req = OrderRequest(
        symbol=mt5_symbol,
        action=signal.action,
        volume=effective_lot_size,
        entry_price=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        comment="AI-Trade",
    )
    
    await tracer.record(
        "order_built",
        input_data={
            "symbol": symbol,
            "mt5_symbol": mt5_symbol,
            "action": signal.action,
            "volume": effective_lot_size,
            "entry": signal.entry,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
        },
    )

    # ── 9. Execute Order via MT5 Executor ─────────────────────────────────
    executor = MT5Executor(creds)
    try:
        executor_result = await executor.execute(order_req)
        await tracer.record(
            "mt5_execution",
            output_data={
                "success": executor_result.success,
                "ticket": executor_result.ticket,
                "error": executor_result.error,
                "mt5_retcode": executor_result.retcode,
            },
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        logger.exception("MT5 Executor raised | account_id=%s ticket=%s", account_id, order_req)
        await tracer.record(
            "mt5_execution", status="error",
            error=str(exc),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
        return signal, journal.id

    if not executor_result.success:
        logger.error(
            "Order failed | MT5 code=%s error=%s | account_id=%s",
            executor_result.retcode, executor_result.error, account_id,
        )
        tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
        return signal, journal.id

    # ── 10. Update Journal & Broadcast trade_opened ───────────────────────
    journal.trade_id = executor_result.ticket  # Using MT5 ticket as trade_id for now
    await db.commit()

    logger.info(
        "Job done: account=%d symbol=%s action=%s order=True ticket=%s",
        account_id, symbol, signal.action, executor_result.ticket
    )
    tracer.finalize(status="completed", final_action=signal.action, journal_id=journal.id, trade_id=executor_result.ticket)
    return signal, journal.id
