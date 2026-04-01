"""AI Trading Service — full pipeline from market data to executed order.

Pipeline per call:
  1. Load account credentials from DB
  2. Kill switch check (fail-fast — in-memory, zero I/O)
  3. Redis rate limit check (LLM path only — 10 calls / 60s per account)
  4. Redis OHLCV cache (TTL by timeframe) — fetch from MT5 on miss
  5. Fetch open positions + recent signals + trade history for LLM memory context
  6. orchestrator.analyze_market() -> LLMAnalysisResult (with position/news context)
  7. Persist to AIJournal (trade_id=None initially)
  8. Broadcast ai_signal WebSocket event
  9. If BUY/SELL: kill switch safety re-check -> MT5Executor -> persist Trade -> update AIJournal
 10. Broadcast trade_opened (if order placed)

Every step is recorded by PipelineTracer to pipeline_runs / pipeline_steps tables.
"""
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import BaseModel as PydanticBase
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import (
    LLMAnalysisResult,
    LLMRoleResult,
    NewsAnalysisResult,
    TradingSignal,
    analyze_market,
    analyze_news_impact,
)
from ai.vision import generate_ohlcv_chart
from core.llm_pricing import compute_cost
from api.routes.ws import broadcast
from core.config import settings
from core.security import decrypt
from db.models import Account, AIJournal, Trade
from db.redis import check_llm_rate_limit, get_candle_cache, set_candle_cache
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import MT5Executor, OrderRequest, pending_expiry_hours
from services.alerting import send_alert
from services.history_sync import HistoryService
from services.kill_switch import is_active as kill_switch_active
from services.pipeline_tracer import PipelineTracer
from strategies.base_strategy import direction_from_action

logger = logging.getLogger(__name__)

# MT5 TIMEFRAME integer constants (from MetaTrader5 Python library)
_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}

# OHLCV cache TTL by timeframe (seconds)
_CACHE_TTL: dict[str, int] = {
    "M1": 30, "M5": 30, "M15": 60, "M30": 120,
    "H1": 300, "H4": 600, "D1": 1800, "W1": 3600,
}

# Minimum lot step for MT5 (universal across brokers)
_MT5_MIN_LOT = 0.01


def _calculate_lot_size(
    balance: float,
    risk_pct: float,
    sl_pips: float,
    pip_value_per_lot: float,
    max_lot: float,
    min_lot: float = _MT5_MIN_LOT,
) -> float:
    """Compute risk-proportional lot size, clamped to [min_lot, max_lot].

    Args:
        balance: Current account balance in account currency.
        risk_pct: Fraction of balance to risk (e.g. 0.01 = 1%).
        sl_pips: Stop-loss distance in pips.
        pip_value_per_lot: Value of 1 pip for a 1.0-lot position in account currency.
        max_lot: Maximum allowed lot size (safety cap from account config).
        min_lot: Minimum MT5 lot step (default 0.01).

    Returns:
        Calculated lot size rounded to nearest min_lot step, between [min_lot, max_lot].
    """
    if balance <= 0 or sl_pips <= 0 or pip_value_per_lot <= 0:
        return min_lot
    raw = (balance * risk_pct) / (sl_pips * pip_value_per_lot)
    raw = round(raw / min_lot) * min_lot  # round to lot step
    return max(min_lot, min(raw, max_lot))


def _provider_name(llm: object) -> str:
    """Derive a short provider name from a LangChain LLM class."""
    mod = type(llm).__module__
    if "openai" in mod:
        return "openai"
    if "google" in mod or "gemini" in mod:
        return "gemini"
    if "anthropic" in mod:
        return "anthropic"
    return "unknown"


async def _get_task_llm(task: str, db: AsyncSession):
    """Load task-specific LLM from DB assignments. Returns None to use env-var default."""
    from sqlalchemy import select as _select
    from db.models import LLMProviderConfig, TaskLLMAssignment
    from core.security import decrypt as _decrypt
    from ai.orchestrator import _build_llm

    assignment = (await db.execute(
        _select(TaskLLMAssignment).where(TaskLLMAssignment.task == task)
    )).scalar_one_or_none()

    if not assignment or not assignment.provider:
        return None

    provider_row = (await db.execute(
        _select(LLMProviderConfig).where(
            LLMProviderConfig.provider == assignment.provider,
            LLMProviderConfig.is_active.is_(True),
        )
    )).scalar_one_or_none()

    if not provider_row:
        return None

    api_key = _decrypt(provider_row.encrypted_api_key)
    return _build_llm(
        provider=assignment.provider,
        api_key=api_key,
        model=assignment.model_name or None,
    )


def _news_direction(action: str) -> str:
    """Map a TradingSignal action to a simple BUY/SELL/HOLD direction for news gate comparison."""
    a = action.upper()
    if a.startswith("BUY"):
        return "BUY"
    if a.startswith("SELL"):
        return "SELL"
    return "HOLD"


class StrategyOverrides(PydanticBase):
    """Per-strategy parameter overrides supplied by the scheduler."""
    lot_size: float | None = None
    sl_pips: float | None = None
    tp_pips: float | None = None
    news_filter: bool = True
    custom_prompt: str | None = None


@dataclass
class AnalysisResult:
    signal: TradingSignal
    order_placed: bool
    ticket: int | None
    journal_id: int


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
    ) -> AnalysisResult:
        """Run the full AI analysis -> optional trade execution pipeline."""
        async with PipelineTracer(account_id, symbol, timeframe, strategy_id=strategy_id) as tracer:
            return await self._run_pipeline(
                tracer, account_id, symbol, timeframe, db, strategy_id, strategy_overrides,
                strategy_instance,
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
    ) -> AnalysisResult:
        """Full instrumented pipeline — every step recorded to PipelineTracer."""

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

        # ── 2. Kill switch check (fail-fast — in-memory, zero I/O) ──────────────
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

        # ── 3. Rate limit check (LLM path only — Redis read, before any I/O) ─────
        if strategy_instance is None:
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

        # ── 4. Resolve timeframe int ─────────────────────────────────────────
        tf_upper = timeframe.upper()
        tf_int = _TIMEFRAME_MAP.get(tf_upper)
        if tf_int is None:
            await tracer.record(
                "timeframe_check", status="error",
                error=f"Unknown timeframe '{timeframe}'",
                output_data={"timeframe": timeframe, "supported": list(_TIMEFRAME_MAP)},
            )
            tracer.finalize(status="failed")
            raise HTTPException(
                status_code=422,
                detail=f"Unknown timeframe '{timeframe}'. Supported: {list(_TIMEFRAME_MAP)}",
            )

        # ── 4. Market open check + OHLCV fetch ───────────────────────────────
        # Always connect to MT5 first to verify trading is allowed before spending
        # LLM tokens. Reuse the same bridge connection for OHLCV on cache miss.
        t0 = time.monotonic()
        candles = await get_candle_cache(account_id, symbol, tf_upper)
        current_price: float | None = None
        ohlcv_source = "cache"
        mt5_symbol: str = symbol
        tick: dict | None = None

        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login, password=password,
            server=account.server, path=account.mt5_path or settings.mt5_path,
        )
        try:
            async with MT5Bridge(creds) as bridge:
                # Resolve broker-specific symbol name (e.g. EURUSD → EURUSD.s)
                mt5_symbol = await bridge.get_broker_symbol(symbol)

                # ── Market open check (fail-fast before any LLM cost) ────────
                t_market = time.monotonic()
                is_open, trade_mode_name = await bridge.is_market_open(mt5_symbol)
                await tracer.record(
                    "market_open_check",
                    output_data={"trade_mode": trade_mode_name, "is_open": is_open},
                    status="ok" if is_open else "skipped",
                    duration_ms=int((time.monotonic() - t_market) * 1000),
                )
                if not is_open:
                    logger.info(
                        "Market closed (%s) — skipping LLM pipeline | account_id=%s symbol=%s",
                        trade_mode_name, account_id, mt5_symbol,
                    )
                    tracer.finalize(status="skipped")
                    raise HTTPException(
                        status_code=503,
                        detail=f"Market is closed for {symbol} (trade_mode={trade_mode_name})",
                    )

                # ── OHLCV fetch (reuses open bridge; skipped on cache hit) ───
                if candles is None:
                    ohlcv_source = "mt5"
                    logger.info("OHLCV cache miss | account_id=%s symbol=%s tf=%s", account_id, symbol, tf_upper)
                    for _attempt in range(2):
                        candles = await bridge.get_rates(mt5_symbol, tf_int, 250)
                        if candles:
                            break
                        if _attempt == 0:
                            logger.warning(
                                "MT5 returned no candles (attempt 1) — retrying in 1 s | symbol=%s tf=%s",
                                mt5_symbol, tf_upper,
                            )
                            import asyncio as _asyncio
                            await _asyncio.sleep(1)
                    tick = await bridge.get_tick(mt5_symbol)

        except HTTPException:
            raise
        except RuntimeError as exc:
            await tracer.record(
                "ohlcv_fetch", status="error",
                input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframe": tf_upper},
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            tracer.finalize(status="failed")
            raise HTTPException(status_code=503, detail=str(exc))
        except ConnectionError as exc:
            await tracer.record(
                "ohlcv_fetch", status="error",
                input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframe": tf_upper},
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            tracer.finalize(status="failed")
            raise HTTPException(status_code=502, detail=str(exc))

        if ohlcv_source == "mt5":
            if not candles:
                await tracer.record(
                    "ohlcv_fetch", status="error",
                    input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframe": tf_upper},
                    error="MT5 returned no candles",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                tracer.finalize(status="failed")
                raise HTTPException(
                    status_code=502,
                    detail=f"MT5 returned no candles for {mt5_symbol} {timeframe}",
                )
            ttl = _CACHE_TTL.get(tf_upper, 60)
            await set_candle_cache(account_id, symbol, tf_upper, candles, ttl)
            if tick:
                current_price = (tick.get("ask", 0) + tick.get("bid", 0)) / 2

        if current_price is None and candles:
            current_price = float(candles[-1].get("close", 0))

        await tracer.record(
            "ohlcv_fetch",
            input_data={"symbol": symbol, "mt5_symbol": mt5_symbol, "timeframe": tf_upper},
            output_data={
                "source": ohlcv_source,
                "candle_count": len(candles or []),
                "current_price": current_price,
            },
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 5. Compute advanced indicators via pandas-ta ─────────────────────
        t0 = time.monotonic()
        
        try:
            import pandas as pd
            import pandas_ta as ta
            
            # Build DataFrame from MT5 candles
            df = pd.DataFrame(candles)
            if not df.empty and len(df) >= 200: # Need enough data for EMA200
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df.set_index("time", inplace=True)
                
                # Compute indicators inline via pandas-ta
                df.ta.ema(length=50, append=True)
                df.ta.ema(length=200, append=True)
                df.ta.rsi(length=14, append=True)
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                df.ta.atr(length=14, append=True)
                df.ta.bbands(length=20, std=2, append=True)
                
                # Extract the latest row
                latest = df.iloc[-1].to_dict()
                
                # Build rich indicator context
                closes = [float(c.get("close", 0)) for c in candles[-20:]]
                indicators = {
                    "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
                    "ema_50": round(latest.get("EMA_50", 0), 5),
                    "ema_200": round(latest.get("EMA_200", 0), 5),
                    "rsi_14": round(latest.get("RSI_14", 0), 2),
                    "macd": round(latest.get("MACD_12_26_9", 0), 5),
                    "macd_histogram": round(latest.get("MACDh_12_26_9", 0), 5),
                    "atr_14": round(latest.get("ATRr_14", 0), 5),
                    "bb_upper": round(latest.get("BBU_20_2.0", 0), 5),
                    "bb_lower": round(latest.get("BBL_20_2.0", 0), 5),
                    "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
                    "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
                    "candle_count": len(candles),
                }
            else:
                # Fallback if pandas-ta calculation cannot be performed due to insufficient data
                logger.warning("Insufficient candles for pandas-ta calculations (need >= 200). Using basic.")
                closes = [float(c.get("close", 0)) for c in candles[-20:]]
                indicators = {
                    "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
                    "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
                    "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
                    "candle_count": len(candles),
                }
        except ImportError:
            logger.warning("pandas or pandas-ta not installed. Falling back to basic indicators.")
            closes = [float(c.get("close", 0)) for c in candles[-20:]]
            indicators = {
                "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
                "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
                "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
                "candle_count": len(candles),
            }
        except Exception as e:
            logger.exception(f"Error computing advanced indicators: {e}")
            closes = [float(c.get("close", 0)) for c in candles[-20:]]
            indicators = {
                "sma_20": round(sum(closes) / len(closes), 5) if closes else 0,
                "recent_high": max(float(c.get("high", 0)) for c in candles[-20:]),
                "recent_low": min(float(c.get("low", 0)) for c in candles[-20:]),
                "candle_count": len(candles),
            }

        # sanitize output from NaNs created by pandas (json.dumps will fail on NaN)
        import math
        indicators = {k: (0.0 if isinstance(v, float) and math.isnan(v) else v) for k, v in indicators.items()}

        await tracer.record(
            "indicators_computed",
            output_data=indicators,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 6. Fetch position context and recent signals ─────────────────────
        t0 = time.monotonic()
        open_positions: list[dict] = []
        try:
            pos_password = decrypt(account.password_encrypted)
            pos_creds = AccountCredentials(
                login=account.login, password=pos_password,
                server=account.server, path=account.mt5_path or settings.mt5_path,
            )
            async with MT5Bridge(pos_creds) as pos_bridge:
                raw_positions = await pos_bridge.get_positions()
            open_positions = [
                {
                    "symbol": p.get("symbol", ""),
                    "direction": "BUY" if p.get("type") == 0 else "SELL",
                    "volume": p.get("volume", 0),
                    "profit": p.get("profit", 0),
                }
                for p in raw_positions
            ]
        except Exception as exc:
            logger.warning(
                "Could not fetch positions for LLM context | account_id=%s: %s", account_id, exc
            )
        await tracer.record(
            "positions_fetched",
            output_data={"positions": open_positions, "count": len(open_positions)},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        t0 = time.monotonic()
        recent_signals: list[dict] = []
        try:
            journal_rows = (
                await db.execute(
                    select(AIJournal)
                    .where(AIJournal.account_id == account_id, AIJournal.symbol == symbol)
                    .order_by(desc(AIJournal.created_at))
                    .limit(5)
                )
            ).scalars().all()
            recent_signals = [
                {
                    "symbol": j.symbol,
                    "signal": j.signal,
                    "confidence": j.confidence,
                    "rationale": j.rationale[:120],
                }
                for j in journal_rows
            ]
        except Exception as exc:
            logger.warning(
                "Could not fetch recent signals for LLM context | account_id=%s: %s", account_id, exc
            )
        await tracer.record(
            "signals_fetched",
            output_data={"signals": recent_signals, "count": len(recent_signals)},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 6.5 Risk Limits Pre-Check ──────────────────────────────────────────
        t0 = time.monotonic()
        from services.risk_manager import load_risk_config, check_position_limit, check_rate_limit
        risk_cfg = await load_risk_config(db)
        
        exceeded_pos, pos_reason = check_position_limit(open_positions, risk_cfg)
        exceeded_rate, rate_reason = False, ""
        if not exceeded_pos:
            exceeded_rate, rate_reason = await check_rate_limit(symbol, risk_cfg, db)
            
        is_risk_blocked = exceeded_pos or exceeded_rate
        blocked_reason = pos_reason if exceeded_pos else rate_reason

        await tracer.record(
            "risk_limit_pre_check",
            output_data={"blocked": is_risk_blocked, "reason": blocked_reason},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 7. Rule-based signal (code strategies that override generate_signal) ─
        rule_based = False
        signal: TradingSignal | None = None

        if is_risk_blocked:
            signal = TradingSignal(
                action="HOLD",
                entry=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                confidence=1.0,
                rationale=f"Risk limit reached: {blocked_reason} — skipping analysis.",
                timeframe=tf_upper,
            )
            rule_based = True

        elif strategy_instance is not None:
            t0 = time.monotonic()
            market_data = {
                "symbol":         symbol,
                "timeframe":      tf_upper,
                "current_price":  current_price or 0,
                "candles":        candles,
                "indicators":     indicators,
                "open_positions": open_positions,
                "recent_signals": recent_signals,
            }
            try:
                rule_result = strategy_instance.generate_signal(market_data)
            except Exception as exc:
                logger.exception(
                    "generate_signal raised | strategy=%s | %s",
                    type(strategy_instance).__name__, exc,
                )
                rule_result = None
            if rule_result is not None:
                rule_based = True
                await tracer.record(
                    "rule_signal",
                    output_data={
                        "strategy":   type(strategy_instance).__name__,
                        "action":     rule_result.get("action"),
                        "confidence": rule_result.get("confidence"),
                        "rationale":  str(rule_result.get("rationale", ""))[:200],
                    },
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                signal = TradingSignal(**rule_result)

            # ── 8. LLM analysis (skipped for rule-based strategies) ───────────────
        llm_result: LLMAnalysisResult | None = None
        if not rule_based:
            news_context_str: str | None = None
            if getattr(settings, "news_enabled", False):
                from services.market_context import fetch_upcoming_events, format_news_context
                events = await fetch_upcoming_events([symbol])
                news_context_str = format_news_context(events) or None

            trade_history_context: str | None = None
            try:
                hist_svc = HistoryService()
                recent_deals = await hist_svc.get_raw_deals(account, days=30)
                out_deals, in_by_pos = HistoryService._pair_deals(recent_deals)
                trade_history_context = HistoryService.format_for_llm(out_deals, in_by_pos, limit=10) or None
            except Exception as exc:
                logger.warning(
                    "Could not fetch trade history for LLM context | account_id=%s: %s", account_id, exc
                )

            # ── RAG Performance Context (self-calibration) ────────────────
            from services.rag_context import build_rag_context
            rag_ctx = await build_rag_context(db, account_id, symbol, tf_upper)
            if rag_ctx:
                trade_history_context = (
                    (trade_history_context + "\n\n" if trade_history_context else "") + rag_ctx
                )

            # ── Fetch per-role LLM assignments from DB ───────────────────
            ma_llm  = await _get_task_llm("market_analysis", db)
            cv_llm  = await _get_task_llm("vision", db)
            ed_llm  = await _get_task_llm("execution_decision", db)
            na_llm  = (
                await _get_task_llm("news_analysis", db)
                if strategy_overrides and strategy_overrides.news_filter
                else None
            )

            # ── News analysis gate (fires only on imminent High-impact events) ──
            news_signal: str | None = None
            if strategy_overrides and strategy_overrides.news_filter:
                from services.market_context import fetch_high_impact_events
                news_events = await fetch_high_impact_events([symbol], minutes=60)
                await tracer.record(
                    "news_fetch",
                    output_data={
                        "events_found": len(news_events),
                        "events": [
                            {
                                "time": e["time"],
                                "currency": e["currency"],
                                "title": e["title"],
                                "impact": e["impact"],
                            }
                            for e in news_events
                        ],
                        "llm_will_run": bool(news_events),
                    },
                )
                if news_events:
                    t0_news = time.monotonic()
                    news_result: NewsAnalysisResult = await analyze_news_impact(
                        events=news_events, symbol=symbol, llm=na_llm
                    )
                    dur_news = int((time.monotonic() - t0_news) * 1000)
                    news_signal = news_result.signal
                    step_id_news = await tracer.record(
                        "news_analysis",
                        output_data={
                            "signal": news_result.signal,
                            "reasoning": news_result.reasoning,
                            "events_count": len(news_events),
                        },
                        duration_ms=dur_news,
                    )
                    if news_result.role_result is not None:
                        rr = news_result.role_result
                        await tracer.record_llm_call(
                            role="news_analysis",
                            provider=rr.provider,
                            model=rr.model,
                            input_tokens=rr.input_tokens,
                            output_tokens=rr.output_tokens,
                            total_tokens=rr.total_tokens,
                            cost_usd=compute_cost(
                                rr.provider, rr.model,
                                rr.input_tokens or 0, rr.output_tokens or 0,
                            ),
                            duration_ms=rr.duration_ms,
                            pipeline_step_id=step_id_news,
                        )

            # ── Fetch Context Timeframe Candles ─────────────────────────
            context_ohlcv: dict[str, list[dict]] = {}
            if strategy_id:
                from db.models import Strategy
                strat_db = await db.get(Strategy, strategy_id)
                if strat_db and strat_db.context_tfs and strat_db.context_tfs != "[]":
                    try:
                        ctx_tfs = json.loads(strat_db.context_tfs)
                        password = decrypt(account.password_encrypted)
                        creds = AccountCredentials(
                            login=account.login, password=password,
                            server=account.server, path=account.mt5_path or settings.mt5_path,
                        )
                        for ctx_tf in ctx_tfs:
                            ctx_tf_upper = ctx_tf.upper()
                            if ctx_tf_upper == tf_upper:
                                continue  # Skip primary TF
                            ctx_candles = await get_candle_cache(account_id, symbol, ctx_tf_upper)
                            if ctx_candles is None:
                                ctx_tf_int = _TIMEFRAME_MAP.get(ctx_tf_upper)
                                if ctx_tf_int is not None:
                                    try:
                                        async with MT5Bridge(creds) as bridge:
                                            mt5_symbol_ctx = await bridge.get_broker_symbol(symbol)
                                            ctx_candles = await bridge.get_rates(mt5_symbol_ctx, ctx_tf_int, 20)
                                    except Exception as exc:
                                        logger.warning("Context TF fetch failed | symbol=%s tf=%s: %s", symbol, ctx_tf_upper, exc)
                                        ctx_candles = []
                                    if ctx_candles:
                                        ttl = _CACHE_TTL.get(ctx_tf_upper, 60)
                                        await set_candle_cache(account_id, symbol, ctx_tf_upper, ctx_candles, ttl)
                            if ctx_candles:
                                context_ohlcv[ctx_tf_upper] = ctx_candles
                    except json.JSONDecodeError:
                        pass

            chart_b64 = generate_ohlcv_chart(candles, symbol, tf_upper) if settings.enable_chart_vision else None

            t0 = time.monotonic()
            llm_result = await analyze_market(
                symbol=symbol,
                timeframe=tf_upper,
                current_price=current_price or 0,
                indicators=indicators,
                ohlcv=candles,
                chart_analysis=chart_b64,
                open_positions=open_positions,
                recent_signals=recent_signals,
                news_context=news_context_str,
                trade_history_context=trade_history_context,
                system_prompt_override=strategy_overrides.custom_prompt if strategy_overrides else None,
                market_analysis_llm=ma_llm,
                chart_vision_llm=cv_llm,
                execution_decision_llm=ed_llm,
                context_ohlcv=context_ohlcv if context_ohlcv else None,
            )
            signal = llm_result.signal

            # ── News filter gate — skip execution if signals contradict ──
            if news_signal and news_signal != "HOLD":
                market_dir = _news_direction(llm_result.signal.action)
                if market_dir != "HOLD" and market_dir != news_signal:
                    await tracer.record(
                        "news_filter_blocked",
                        output_data={
                            "news_signal": news_signal,
                            "market_signal": llm_result.signal.action,
                            "reason": (
                                f"News analysis ({news_signal}) contradicts "
                                f"market analysis ({market_dir}) — trade skipped"
                            ),
                        },
                    )
                    logger.info(
                        "News filter blocked trade | symbol=%s news=%s market=%s",
                        symbol, news_signal, market_dir,
                    )
                    return AnalysisResult(signal=signal, order_placed=False)

            # ── Record 3 LLM pipeline steps + llm_calls rows ─────────────
            async def _record_llm_role(
                role_result: LLMRoleResult,
                step_name: str,
                role: str,
                input_summary: dict,
            ) -> None:
                input_payload = input_summary
                if getattr(role_result, "prompt", None):
                    input_payload = {
                        "summary": input_summary,
                        "prompt": role_result.prompt
                    }

                step_id = await tracer.record(
                    step_name,
                    input_data=input_payload,
                    output_data={
                        "model":         role_result.model,
                        "provider":      role_result.provider,
                        "input_tokens":  role_result.input_tokens,
                        "output_tokens": role_result.output_tokens,
                        "total_tokens":  role_result.total_tokens,
                        "content": (
                            role_result.content
                            if isinstance(role_result.content, dict)
                            else str(role_result.content)[:500]
                        ),
                    },
                    duration_ms=role_result.duration_ms,
                )
                cost = (
                    compute_cost(
                        role_result.model,
                        role_result.input_tokens or 0,
                        role_result.output_tokens or 0,
                    )
                    if role_result.input_tokens is not None
                    else None
                )
                await tracer.record_llm_call(
                    role=role,
                    provider=role_result.provider,
                    model=role_result.model,
                    input_tokens=role_result.input_tokens,
                    output_tokens=role_result.output_tokens,
                    total_tokens=role_result.total_tokens,
                    cost_usd=cost,
                    duration_ms=role_result.duration_ms,
                    pipeline_step_id=step_id,
                )

            await _record_llm_role(
                llm_result.market_analysis,
                "market_analysis_llm",
                "market_analysis",
                {"symbol": symbol, "timeframe": tf_upper},
            )
            if llm_result.chart_vision is not None:
                await _record_llm_role(
                    llm_result.chart_vision,
                    "chart_vision_llm",
                    "chart_vision",
                    {"symbol": symbol, "has_image": True, "chart_b64": chart_b64},
                )
            if llm_result.indicator_agent is not None:
                await _record_llm_role(
                    llm_result.indicator_agent,
                    "indicator_agent_llm",
                    "indicator_agent",
                    {"symbol": symbol, "timeframe": tf_upper},
                )
            if llm_result.pattern_agent is not None:
                await _record_llm_role(
                    llm_result.pattern_agent,
                    "pattern_agent_llm",
                    "pattern_agent",
                    {"symbol": symbol, "has_chart": True, "chart_b64": chart_b64},
                )
            if llm_result.trend_agent is not None:
                # trendline_chart_b64 is only available in the agent pipeline path
                tl_b64 = getattr(llm_result, "trendline_chart_b64", None)
                await _record_llm_role(
                    llm_result.trend_agent,
                    "trend_agent_llm",
                    "trend_agent",
                    {"symbol": symbol, "has_trendline_chart": True, **({"chart_b64": tl_b64} if tl_b64 else {})},
                )
            await _record_llm_role(
                llm_result.execution_decision,
                "execution_decision_llm",
                "execution_decision",
                {
                    "action":     signal.action,
                    "confidence": signal.confidence,
                },
            )

        # ── 9. Confidence gate ───────────────────────────────────────────────
        assert signal is not None, "signal must be set by either rule-based or LLM path"
        action_before = signal.action
        if signal.confidence < settings.llm_confidence_threshold:
            logger.info(
                "Signal downgraded to HOLD — confidence %.2f below threshold %.2f | symbol=%s",
                signal.confidence, settings.llm_confidence_threshold, symbol,
            )
            signal.action = "HOLD"
        await tracer.record(
            "confidence_gate",
            input_data={
                "confidence": signal.confidence,
                "threshold": settings.llm_confidence_threshold,
            },
            output_data={"action_before": action_before, "action_after": signal.action},
        )

        logger.info(
            "Signal result | symbol=%s action=%s confidence=%.2f timeframe=%s",
            symbol, signal.action, signal.confidence, signal.timeframe,
        )

        # ── 9. Persist AIJournal ─────────────────────────────────────────────
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
            llm_provider="rule_based" if rule_based else (
                llm_result.execution_decision.provider if llm_result is not None else settings.llm_provider
            ),
            model_name=(
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
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id
            )

        # ── 12. Kill switch safety re-check (race condition: activated during LLM analysis) ──
        ks_active = kill_switch_active()
        await tracer.record("kill_switch_check", output_data={"active": ks_active})
        if ks_active:
            logger.warning(
                "Kill switch active — signal saved but order skipped | account_id=%s symbol=%s",
                account_id, symbol,
            )
            tracer.finalize(status="skipped", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id
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
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id
            )

        # ── 14. Build credentials (needed for lot-size fetch + order execution) ─
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login, password=password,
            server=account.server, path=account.mt5_path or settings.mt5_path,
        )

        # ── 15. Dynamic lot size ──────────────────────────────────────────────
        # Priority: strategy_overrides.lot_size > risk-based calc > max_lot_size fallback
        t0 = time.monotonic()
        sl_pips: float | None = None
        pip_value_per_lot: float | None = None
        balance: float | None = None
        if strategy_overrides and strategy_overrides.lot_size is not None:
            effective_lot_size = strategy_overrides.lot_size
        else:
            effective_lot_size = account.max_lot_size  # safe fallback
            try:
                async with MT5Bridge(creds) as lot_bridge:
                    acct_info = await lot_bridge.get_account_info()
                    sym_info = await lot_bridge.get_symbol_info(mt5_symbol)
                if acct_info and sym_info:
                    balance = float(acct_info.get("balance", 0))
                    tick_value = float(sym_info.get("trade_tick_value", 0))
                    tick_size = float(sym_info.get("trade_tick_size", 0))
                    # Normalise SL distance to pips (1 pip = 10 × tick_size for 5-digit brokers)
                    pip_size = tick_size * 10 if tick_size > 0 else 0.0001
                    sl_distance = abs((signal.entry or 0) - (signal.stop_loss or 0))
                    sl_pips = sl_distance / pip_size if pip_size > 0 else 0
                    # trade_tick_value is already in account currency for 1 pip on 1 lot
                    pip_value_per_lot = tick_value
                    effective_lot_size = _calculate_lot_size(
                        balance=balance,
                        risk_pct=account.risk_pct,
                        sl_pips=sl_pips,
                        pip_value_per_lot=pip_value_per_lot,
                        max_lot=account.max_lot_size,
                    )
                    logger.info(
                        "Lot size calculated | account_id=%s balance=%.2f risk_pct=%.3f "
                        "sl_pips=%.1f pip_val=%.4f → lot=%.2f",
                        account_id, balance, account.risk_pct, sl_pips, pip_value_per_lot, effective_lot_size,
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
                "formula": f"{balance} * {account.risk_pct} * {sl_pips} * {pip_value_per_lot} / {account.max_lot_size} = {effective_lot_size}",
            },
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        _source = "ai"
        if strategy_id:
            from db.models import Strategy as _Strategy
            _strat_rec = await db.get(_Strategy, strategy_id)
            if _strat_rec:
                _source = _strat_rec.name
        order_req = OrderRequest(
            symbol=mt5_symbol,  # broker-specific name resolved at OHLCV fetch time
            action=signal.action,
            volume=effective_lot_size,
            entry_price=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            comment=_source[:64],
            expiration_hours=pending_expiry_hours(timeframe),
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
                "expiration_hours": pending_expiry_hours(timeframe),
                "comment": _source[:64],
            },
        )

        # ── 16. Connect MT5 and execute ──────────────────────────────────────
        t0 = time.monotonic()
        try:
            async with MT5Bridge(creds) as bridge:
                executor = MT5Executor(bridge)
                order_result = await executor.place_order(
                    order_req, dry_run=account.paper_trade_enabled
                )
            # await tracer.record(
            #     "mt5_executed", status="success",
            #     output_data=order_result,
            #     duration_ms=int((time.monotonic() - t0) * 1000),
            # )
        except (RuntimeError, ConnectionError) as exc:
            logger.exception("MT5 error during order execution | account_id=%s | %s", account_id, exc)
            await tracer.record(
                "mt5_executed", status="error",
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id
            )

        if not order_result.success:
            logger.error(
                "Order failed | account_id=%s symbol=%s error=%s",
                account_id, symbol, order_result.error,
            )
            await tracer.record(
                "mt5_executed", status="error",
                output_data={"success": False, "error": order_result.error},
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            await send_alert(
                f"*Order Failed*\n"
                f"Account: {account_id} | {signal.action} {symbol}\n"
                f"Error: {order_result.error}"
            )
            tracer.finalize(status="failed", final_action=signal.action, journal_id=journal.id)
            return AnalysisResult(
                signal=signal, order_placed=False, ticket=None, journal_id=journal.id
            )

        await tracer.record(
            "mt5_executed",
            output_data={
                "success": True,
                "ticket": order_result.ticket,
                "paper_trade": account.paper_trade_enabled,
            },
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

        # ── 16. Persist Trade row ────────────────────────────────────────────
        _action = signal.action.upper()
        _is_pending = _action in {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
        _order_type = (
            "limit" if "LIMIT" in _action
            else "stop" if "STOP" in _action
            else "market"
        )
        trade = Trade(
            account_id=account_id,
            ticket=order_result.ticket,
            symbol=symbol,
            direction=direction_from_action(signal.action),
            volume=effective_lot_size,
            entry_price=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            opened_at=datetime.now(UTC),
            source=_source,
            is_paper_trade=account.paper_trade_enabled,
            strategy_id=strategy_id,
            order_type=_order_type,
            order_status="pending" if _is_pending else "filled",
        )
        db.add(trade)
        await db.flush()

        journal.trade_id = trade.id
        await db.commit()
        await db.refresh(trade)

        # ── 17. Broadcast trade_opened ───────────────────────────────────────
        await broadcast(account_id, "trade_opened", {
            "ticket": order_result.ticket,
            "symbol": symbol,
            "direction": direction_from_action(signal.action),
            "action": signal.action,
            "volume": effective_lot_size,
            "entry_price": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        })

        # ── 18. Send Telegram alert ──────────────────────────────────────────
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
        )
