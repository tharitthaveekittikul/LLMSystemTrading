"""Signal generation phase for the AI trading pipeline.

Covers:
- Shared-context fast path (secondary group accounts)
- Risk limit pre-check (step 6.5)
- Rule-based signal path (step 7)
- LLM analysis path (step 8): news gate, context TF fetch, core LLM call,
  news filter gate, per-role recording, SharedMarketContext construction
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import LLMAnalysisResult, NewsAnalysisResult, TradingSignal, analyze_market, analyze_news_impact
from core.config import settings
from core.llm_pricing import compute_cost
from services.ai_trading._helpers import _get_task_llm, _news_direction, record_llm_role
from services.ai_trading._market_data import fetch_context_ohlcv, maybe_chart
from services.ai_trading._models import SharedMarketContext, StrategyOverrides

if TYPE_CHECKING:
    from db.models import Account
    from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)


# ── Public dataclass ──────────────────────────────────────────────────────────

@dataclass
class SignalPhaseResult:
    signal: TradingSignal
    mt5_symbol: str
    candles: list[dict]
    indicators: dict
    current_price: float
    llm_result: LLMAnalysisResult | None
    rule_based: bool
    news_signal: str | None
    built_shared_ctx: SharedMarketContext | None


# ── Private: LLM analysis path ────────────────────────────────────────────────

async def _run_llm_analysis(
    *,
    account: "Account",
    account_id: int,
    symbol: str,
    tf_upper: str,
    strategy_id: int | None,
    strategy_overrides: "StrategyOverrides | None",
    open_positions: list[dict],
    recent_signals: list[dict],
    trade_history_context: str | None,
    candles: list[dict],
    indicators: dict,
    current_price: float,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> tuple[LLMAnalysisResult, str | None]:
    """Run full LLM analysis. Returns (llm_result, news_signal)."""

    # ── Fetch news context string (upcoming events) ──────────────────────
    news_context_str: str | None = None
    if getattr(settings, "news_enabled", False):
        from services.market_context import fetch_upcoming_events, format_news_context
        events = await fetch_upcoming_events([symbol])
        news_context_str = format_news_context(events) or None

    # ── Fetch per-role LLM assignments from DB ───────────────────────────
    ma_llm = await _get_task_llm("market_analysis", db)
    cv_llm = await _get_task_llm("vision", db)
    ed_llm = await _get_task_llm("execution_decision", db)
    na_llm = (
        await _get_task_llm("news_analysis", db)
        if strategy_overrides and strategy_overrides.news_filter
        else None
    )

    # ── News analysis gate (fires only on imminent High-impact events) ───
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

    # ── Fetch context timeframe candles ──────────────────────────────────
    context_ohlcv: dict[str, list[dict]] = await fetch_context_ohlcv(
        account=account,
        account_id=account_id,
        symbol=symbol,
        primary_tf=tf_upper,
        strategy_id=strategy_id,
        db=db,
    )

    # ── Optional chart generation ────────────────────────────────────────
    chart_b64 = maybe_chart(candles, symbol, tf_upper)

    # ── Core LLM call ────────────────────────────────────────────────────
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

    # ── News filter gate — skip execution if signals contradict ─────────
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
            llm_result.signal.action = "HOLD"
            return llm_result, news_signal

    # ── Record per-role LLM pipeline steps + llm_calls rows ─────────────
    await record_llm_role(
        tracer,
        llm_result.market_analysis,
        "market_analysis_llm",
        "market_analysis",
        {"symbol": symbol, "timeframe": tf_upper},
    )
    if llm_result.chart_vision is not None:
        await record_llm_role(
            tracer,
            llm_result.chart_vision,
            "chart_vision_llm",
            "chart_vision",
            {"symbol": symbol, "has_image": True, "chart_b64": chart_b64},
        )
    if llm_result.indicator_agent is not None:
        await record_llm_role(
            tracer,
            llm_result.indicator_agent,
            "indicator_agent_llm",
            "indicator_agent",
            {"symbol": symbol, "timeframe": tf_upper},
        )
    if llm_result.pattern_agent is not None:
        await record_llm_role(
            tracer,
            llm_result.pattern_agent,
            "pattern_agent_llm",
            "pattern_agent",
            {"symbol": symbol, "has_chart": True, "chart_b64": chart_b64},
        )
    if llm_result.trend_agent is not None:
        tl_b64 = getattr(llm_result, "trendline_chart_b64", None)
        await record_llm_role(
            tracer,
            llm_result.trend_agent,
            "trend_agent_llm",
            "trend_agent",
            {"symbol": symbol, "has_trendline_chart": True, **({"chart_b64": tl_b64} if tl_b64 else {})},
        )
    await record_llm_role(
        tracer,
        llm_result.execution_decision,
        "execution_decision_llm",
        "execution_decision",
        {
            "action": llm_result.signal.action,
            "confidence": llm_result.signal.confidence,
        },
    )

    return llm_result, news_signal


# ── Public entry point ────────────────────────────────────────────────────────

async def run_signal_phase(
    *,
    account: "Account",
    account_id: int,
    symbol: str,
    tf_upper: str,
    strategy_id: int | None,
    strategy_overrides: "StrategyOverrides | None",
    strategy_instance: object | None,
    shared_ctx: SharedMarketContext | None,
    open_positions: list[dict],
    recent_signals: list[dict],
    trade_history_context: str | None,
    candles: list[dict],
    indicators: dict,
    current_price: float,
    mt5_symbol: str,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> SignalPhaseResult:
    """Run the full signal generation phase.

    Returns a SignalPhaseResult with the chosen signal and supporting metadata.
    """

    # ── Fast path: shared context provided by primary account ────────────
    if shared_ctx is not None:
        signal = shared_ctx.signal.model_copy()
        await tracer.record(
            "shared_signal_received",
            output_data={
                "action": signal.action,
                "confidence": signal.confidence,
                "rationale": signal.rationale[:200] if signal.rationale else "",
                "source": "llm" if shared_ctx.llm_result else "rule",
            },
        )
        return SignalPhaseResult(
            signal=signal,
            mt5_symbol=shared_ctx.mt5_symbol,
            candles=shared_ctx.candles,
            indicators=shared_ctx.indicators,
            current_price=shared_ctx.current_price,
            llm_result=shared_ctx.llm_result,
            rule_based=shared_ctx.llm_result is None,
            news_signal=shared_ctx.news_signal,
            built_shared_ctx=None,
        )

    # ── Normal path ───────────────────────────────────────────────────────
    news_signal: str | None = None

    # ── 6.5 Risk limits pre-check ─────────────────────────────────────────
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

    # ── 7. Rule-based signal ──────────────────────────────────────────────
    rule_based = False
    signal: TradingSignal | None = None
    llm_result: LLMAnalysisResult | None = None

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

    # ── 8. LLM analysis (skipped for rule-based strategies) ──────────────
    if not rule_based:
        llm_result, news_signal = await _run_llm_analysis(
            account=account,
            account_id=account_id,
            symbol=symbol,
            tf_upper=tf_upper,
            strategy_id=strategy_id,
            strategy_overrides=strategy_overrides,
            open_positions=open_positions,
            recent_signals=recent_signals,
            trade_history_context=trade_history_context,
            candles=candles,
            indicators=indicators,
            current_price=current_price,
            db=db,
            tracer=tracer,
        )
        signal = llm_result.signal

    # ── Build SharedMarketContext ─────────────────────────────────────────
    built_shared_ctx = SharedMarketContext(
        symbol=symbol,
        mt5_symbol=mt5_symbol,
        timeframe=tf_upper,
        candles=candles,
        indicators=indicators,
        current_price=current_price or 0.0,
        signal=signal,
        llm_result=llm_result,
        news_signal=news_signal,
    )

    return SignalPhaseResult(
        signal=signal,
        mt5_symbol=mt5_symbol,
        candles=candles,
        indicators=indicators,
        current_price=current_price or 0.0,
        llm_result=llm_result,
        rule_based=rule_based,
        news_signal=news_signal,
        built_shared_ctx=built_shared_ctx,
    )
