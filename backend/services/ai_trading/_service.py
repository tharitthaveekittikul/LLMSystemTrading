"""AI Trading Service — orchestrator pipeline.

Delegates all heavy lifting to the extracted sub-modules; this file is
intentionally ~120 lines of glue logic only.
"""
import json
import logging
import time

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.ws import broadcast
from core.config import settings
from core.security import decrypt
from db.models import AIJournal
from db.redis import check_llm_rate_limit
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import TRADE_RETCODE_INVALID_PRICE, OrderResult
from services.ai_trading._context import (
    build_trade_history_context,
    fetch_open_positions,
    fetch_recent_signals,
)
from services.ai_trading._execution import (
    build_order_request,
    compute_lot_size,
    execute_mt5_order,
    persist_trade,
)
from services.ai_trading._market_data import compute_indicators, fetch_ohlcv, resolve_timeframe
from services.ai_trading._models import AnalysisResult, SharedMarketContext, StrategyOverrides
from services.ai_trading._signal import SignalPhaseResult, run_signal_phase
from services.alerting import send_alert
from services.kill_switch import is_active as kill_switch_active
from services.pipeline_tracer import PipelineTracer
from services.research_loop import effective_confidence_threshold, get_symbol_trust_score

logger = logging.getLogger(__name__)


class AITradingService:
    async def analyze_and_trade(
        self,
        account_id: int,
        symbol: str,
        timeframe: str,
        db: AsyncSession,
        strategy_id: int | None = None,
        strategy_overrides: "StrategyOverrides | None" = None,
        strategy_instance: object | None = None,
        shared_ctx: "SharedMarketContext | None" = None,
    ) -> AnalysisResult:
        """Run the full AI analysis -> optional trade execution pipeline."""
        async with PipelineTracer(account_id, symbol, timeframe, strategy_id=strategy_id) as tracer:
            return await self._run_pipeline(
                tracer, account_id, symbol, timeframe, db, strategy_id, strategy_overrides,
                strategy_instance,
                shared_ctx=shared_ctx,
            )

    async def _run_pipeline(
        self,
        tracer: PipelineTracer,
        account_id: int,
        symbol: str,
        timeframe: str,
        db: AsyncSession,
        strategy_id: int | None,
        strategy_overrides: "StrategyOverrides | None",
        strategy_instance: object | None = None,
        shared_ctx: "SharedMarketContext | None" = None,
    ) -> AnalysisResult:
        """Full instrumented pipeline — every step recorded to PipelineTracer."""
        from db.models import Account

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
            raise HTTPException(status_code=404, detail="Account not found")
        await tracer.record(
            "account_loaded",
            output_data={
                "name": account.name,
                "auto_trade_enabled": account.auto_trade_enabled,
                "max_lot_size": account.max_lot_size,
            },
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 2. Kill switch check (fail-fast — in-memory, zero I/O) ──────────
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
            raise HTTPException(status_code=503, detail="Kill switch is active — trading halted")

        # ── 3. Rate limit check (LLM path only — Redis read, before any I/O) ─
        if strategy_instance is None and shared_ctx is None:
            t0 = time.monotonic()
            allowed = await check_llm_rate_limit(account_id)
            if not allowed:
                await tracer.record(
                    "rate_limit_check", status="error",
                    output_data={"allowed": False},
                    error="LLM rate limit exceeded",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                tracer.finalize(status="failed")
                logger.warning("LLM rate limit exceeded | account_id=%s", account_id)
                raise HTTPException(
                    status_code=429,
                    detail="LLM rate limit exceeded — max 10 calls per 60 seconds per account",
                )
            await tracer.record(
                "rate_limit_check",
                output_data={"allowed": True},
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        # ── 3.5 Determine whether to skip analysis (shared-context fast path) ─
        _skip_analysis = shared_ctx is not None

        # ── 4–6. Market data + context (skipped for shared-ctx secondary accounts) ─
        candles: list[dict] = []
        mt5_symbol: str = symbol
        current_price: float | None = None
        indicators: dict = {}
        open_positions: list[dict] = []
        recent_signals: list[dict] = []
        trade_history_context: str | None = None

        if not _skip_analysis:
            # 4. Resolve timeframe
            tf_upper, tf_int = resolve_timeframe(timeframe)

            # 4–5. Fetch OHLCV (market open check + cache/MT5)
            candles, mt5_symbol, current_price = await fetch_ohlcv(
                account=account,
                account_id=account_id,
                symbol=symbol,
                tf_upper=tf_upper,
                tf_int=tf_int,
                tracer=tracer,
            )

            # 5. Compute indicators
            t0 = time.monotonic()
            indicators = compute_indicators(candles)
            await tracer.record(
                "indicators_computed",
                output_data=indicators,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

            # 6. Fetch open positions + recent signals + trade history
            open_positions = await fetch_open_positions(account=account, account_id=account_id, tracer=tracer)
            recent_signals = await fetch_recent_signals(account_id=account_id, symbol=symbol, db=db, tracer=tracer)
            trade_history_context = await build_trade_history_context(
                account=account,
                account_id=account_id,
                symbol=symbol,
                tf_upper=timeframe.upper(),
                db=db,
                tracer=tracer,
            )
        else:
            tf_upper = shared_ctx.timeframe  # type: ignore[union-attr]

        # ── 7–8. Signal phase ────────────────────────────────────────────────
        spr: SignalPhaseResult = await run_signal_phase(
            account=account,
            account_id=account_id,
            symbol=symbol,
            tf_upper=tf_upper,
            strategy_id=strategy_id,
            strategy_overrides=strategy_overrides,
            strategy_instance=strategy_instance,
            shared_ctx=shared_ctx,
            open_positions=open_positions,
            recent_signals=recent_signals,
            trade_history_context=trade_history_context,
            candles=candles,
            indicators=indicators,
            current_price=current_price or 0.0,
            mt5_symbol=mt5_symbol,
            db=db,
            tracer=tracer,
        )

        signal = spr.signal
        mt5_symbol = spr.mt5_symbol
        candles = spr.candles
        indicators = spr.indicators
        current_price = spr.current_price
        llm_result = spr.llm_result
        rule_based = spr.rule_based
        _built_shared_ctx = spr.built_shared_ctx

        # ── 9. Confidence gate ───────────────────────────────────────────────
        action_before = signal.action
        trust_score = get_symbol_trust_score(symbol)
        gate_threshold = effective_confidence_threshold(symbol, settings.llm_confidence_threshold)
        if signal.confidence < gate_threshold:
            logger.info(
                "Signal downgraded to HOLD — confidence %.2f below effective threshold %.2f "
                "(base=%.2f trust_score=%.2f) | symbol=%s",
                signal.confidence, gate_threshold, settings.llm_confidence_threshold,
                trust_score, symbol,
            )
            signal.action = "HOLD"
        await tracer.record(
            "confidence_gate",
            input_data={
                "confidence": signal.confidence,
                "base_threshold": settings.llm_confidence_threshold,
                "effective_threshold": gate_threshold,
                "symbol_trust_score": trust_score,
            },
            output_data={"action_before": action_before, "action_after": signal.action},
        )

        logger.info(
            "Signal result | symbol=%s action=%s confidence=%.2f timeframe=%s",
            symbol, signal.action, signal.confidence, signal.timeframe,
        )

        # ── 9b. Persist AIJournal ────────────────────────────────────────────
        t0 = time.monotonic()
        journal = AIJournal(
            account_id=account_id,
            trade_id=None,
            symbol=symbol,
            timeframe=tf_upper,
            signal=signal.action,
            confidence=signal.confidence,
            rationale=signal.rationale,
            indicators_snapshot=json.dumps(indicators),
            llm_provider="group_llm" if _skip_analysis else (
                "rule_based" if rule_based else (
                    llm_result.execution_decision.provider if llm_result is not None else settings.llm_provider
                )
            ),
            model_name="shared" if _skip_analysis else (
                type(strategy_instance).__name__ if rule_based
                else (llm_result.execution_decision.model if llm_result is not None else "")
            ),
            strategy_id=strategy_id,
        )
        db.add(journal)
        await db.commit()
        await db.refresh(journal)
        await tracer.record(
            "journal_saved",
            output_data={"journal_id": journal.id},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 10. Broadcast ai_signal ──────────────────────────────────────────
        await broadcast(account_id, "ai_signal", {
            "journal_id": journal.id,
            "symbol": symbol,
            "timeframe": tf_upper,
            "action": signal.action,
            "confidence": signal.confidence,
            "rationale": signal.rationale,
            "entry": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        })

        # ── 11. Skip if HOLD ─────────────────────────────────────────────────
        if signal.action == "HOLD":
            await tracer.record(
                "kill_switch_check",
                output_data={"active": False, "skipped": "HOLD signal"},
            )
            logger.info("Signal HOLD — no order | account_id=%s symbol=%s", account_id, symbol)
            tracer.finalize(status="hold", final_action="HOLD", journal_id=journal.id)
            return AnalysisResult(
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id,
                shared_ctx=_built_shared_ctx,
            )

        # ── 12. Kill switch re-check (race condition guard) ──────────────────
        ks_active = kill_switch_active()
        await tracer.record("kill_switch_check", output_data={"active": ks_active})
        if ks_active:
            logger.warning(
                "Kill switch active — signal saved but order skipped | account_id=%s symbol=%s",
                account_id, symbol,
            )
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id,
                shared_ctx=_built_shared_ctx,
            )

        # ── 13. Auto-trade disabled check ────────────────────────────────────
        if not account.auto_trade_enabled:
            await tracer.record(
                "auto_trade_check",
                status="skipped",
                output_data={"auto_trade_enabled": False},
                error="Auto-trade is disabled on this account — signal saved but no order placed",
            )
            logger.info(
                "Auto-trade disabled — signal saved but order skipped | account_id=%s",
                account_id,
            )
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id,
                shared_ctx=_built_shared_ctx,
            )

        # ── 14–15. Lot size + order request ─────────────────────────────────
        effective_lot_size = await compute_lot_size(
            account=account,
            account_id=account_id,
            signal=signal,
            mt5_symbol=mt5_symbol,
            strategy_overrides=strategy_overrides,
            tracer=tracer,
        )

        order_req, _source = await build_order_request(
            signal=signal,
            mt5_symbol=mt5_symbol,
            effective_lot_size=effective_lot_size,
            timeframe=timeframe,
            account_id=account_id,
            strategy_id=strategy_id,
            db=db,
            tracer=tracer,
        )

        # ── 16. Execute MT5 order ────────────────────────────────────────────
        order_result = await execute_mt5_order(
            account=account,
            order_req=order_req,
            signal=signal,
            journal=journal,
            built_shared_ctx=_built_shared_ctx,
            tracer=tracer,
        )

        # Stale pending entry → re-request LLM with live market price (one retry)
        if isinstance(order_result, OrderResult) and order_result.retcode == TRADE_RETCODE_INVALID_PRICE:
            logger.warning(
                "Stale pending — re-requesting LLM with live price | "
                "account_id=%s symbol=%s original_entry=%s",
                account_id, mt5_symbol, signal.entry,
            )
            _password = decrypt(account.password_encrypted)
            _creds = AccountCredentials(
                login=account.login, password=_password,
                server=account.server, path=account.mt5_path or settings.mt5_path,
            )
            live_price: float | None = None
            async with MT5Bridge(_creds) as _bridge:
                _tick = await _bridge.get_tick(mt5_symbol)
                if _tick:
                    live_price = _tick.get("ask") if "BUY" in signal.action else _tick.get("bid")

            if live_price:
                await tracer.record(
                    "stale_entry_retry",
                    input_data={"original_entry": signal.entry, "live_price": live_price},
                )
                spr2 = await run_signal_phase(
                    account=account, account_id=account_id, symbol=symbol, tf_upper=tf_upper,
                    strategy_id=strategy_id, strategy_overrides=strategy_overrides,
                    strategy_instance=strategy_instance, shared_ctx=shared_ctx,
                    open_positions=open_positions, recent_signals=recent_signals,
                    trade_history_context=trade_history_context, candles=candles,
                    indicators=indicators, current_price=live_price, mt5_symbol=mt5_symbol,
                    db=db, tracer=tracer,
                )
                signal = spr2.signal
                if signal.confidence < effective_confidence_threshold(symbol, settings.llm_confidence_threshold):
                    signal.action = "HOLD"

                if signal.action == "HOLD":
                    tracer.finalize(status="hold", final_action="HOLD", journal_id=journal.id)
                    return AnalysisResult(
                        signal=signal, order_placed=False, ticket=None,
                        journal_id=journal.id, shared_ctx=_built_shared_ctx,
                    )

                effective_lot_size = await compute_lot_size(
                    account=account, account_id=account_id, signal=signal,
                    mt5_symbol=mt5_symbol, strategy_overrides=strategy_overrides, tracer=tracer,
                )
                order_req, _source = await build_order_request(
                    signal=signal, mt5_symbol=mt5_symbol, effective_lot_size=effective_lot_size,
                    timeframe=timeframe, account_id=account_id, strategy_id=strategy_id,
                    db=db, tracer=tracer,
                )
                order_result = await execute_mt5_order(
                    account=account, order_req=order_req, signal=signal,
                    journal=journal, built_shared_ctx=_built_shared_ctx, tracer=tracer,
                )
            else:
                tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
                order_result = None

        if order_result is None:
            return AnalysisResult(
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id,
                shared_ctx=_built_shared_ctx,
            )

        # ── 16b. Persist trade ───────────────────────────────────────────────
        trade = await persist_trade(
            account_id=account_id,
            signal=signal,
            order_result=order_result,
            effective_lot_size=effective_lot_size,
            symbol=symbol,
            strategy_id=strategy_id,
            source=_source,
            paper_trade=account.paper_trade_enabled,
            db=db,
            journal=journal,
        )

        # ── 17. Broadcast trade_opened ───────────────────────────────────────
        await broadcast(account_id, "trade_opened", {
            "ticket": order_result.ticket,
            "symbol": symbol,
            "direction": trade.direction,
            "action": signal.action,
            "volume": effective_lot_size,
            "entry_price": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        })

        # ── 18. Telegram alert ───────────────────────────────────────────────
        t0 = time.monotonic()
        paper_tag = " _(paper)_" if account.paper_trade_enabled else ""
        alert_msg = (
            f"*Trade Placed{paper_tag}*\n"
            f"Account: {account_id} | {signal.action} {effective_lot_size} {symbol}\n"
            f"Entry: {signal.entry} | SL: {signal.stop_loss} | TP: {signal.take_profit}\n"
            f"Ticket: {order_result.ticket}"
        )
        await send_alert(alert_msg)
        await tracer.record(
            "telegram_sent",
            output_data={"sent": True, "preview": alert_msg[:100]},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        logger.info(
            "Trade executed | account_id=%s symbol=%s direction=%s ticket=%s",
            account_id, symbol, signal.action, order_result.ticket,
        )

        tracer.finalize(
            status="completed",
            final_action=signal.action,
            journal_id=journal.id,
            trade_id=trade.id,
        )
        return AnalysisResult(
            signal=signal,
            order_placed=True,
            ticket=order_result.ticket,
            journal_id=journal.id,
            shared_ctx=_built_shared_ctx,
        )
