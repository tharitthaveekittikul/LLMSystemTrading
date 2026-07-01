"""Per-role prompt builders and the public analyze/review/pipeline entry points."""
import json
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ai.orchestrator._llm import (
    _build_llm,
    _call_llm_for_role,
    _model_name_from_llm,
    _provider_from_llm,
)
from ai.orchestrator._models import (
    LLMAnalysisResult,
    LLMRoleResult,
    MaintenanceDecision,
    MaintenanceResult,
    NewsAnalysisResult,
    TradingSignal,
)
from ai.orchestrator._parsing import _normalize_raw
from ai.orchestrator._prompts import (
    _EXECUTION_SYSTEM,
    _MAINTENANCE_DECISION_SYSTEM,
    _MAINTENANCE_SENTIMENT_SYSTEM,
    _MAINTENANCE_TECHNICAL_SYSTEM,
    _MARKET_ANALYSIS_SYSTEM,
)
from core.config import settings
from services.research_loop import effective_confidence_threshold

logger = logging.getLogger(__name__)


# ── Role: Market Analysis ──────────────────────────────────────────────────────

async def _run_market_analysis(
    llm: BaseChatModel,
    symbol: str,
    timeframe: str,
    current_price: float,
    indicators: dict,
    ohlcv: list[dict],
    open_positions: list[dict],
    recent_signals: list[dict],
    news_context: str | None,
    trade_history_context: str | None,
    context_ohlcv: dict[str, list[dict]] | None = None,
) -> LLMRoleResult:
    """LLM Role 1: Analyze market conditions and produce a context summary."""
    pos_lines = [
        f"  - {p.get('symbol', symbol)} {p.get('direction','?')} vol={p.get('volume','?')} profit={p.get('profit','?')}"
        for p in (open_positions or [])
    ] or ["  None"]
    sig_lines = [
        f"  - {s.get('symbol',symbol)} {s.get('signal','?')} conf={s.get('confidence','?')} | {s.get('rationale','')[:80]}"
        for s in (recent_signals or [])
    ]

    human_parts = [
        f"Symbol: {symbol}\nPrimary Timeframe: {timeframe}\nCurrent Price: {current_price}",
        f"\nIndicators (Primary {timeframe}):\n{json.dumps(indicators, indent=2)}",
    ]
    human_parts.append(f"\nLast 20 OHLCV candles ({timeframe}) (oldest → newest):\n{json.dumps(ohlcv[-20:], indent=2, default=str)}")

    if context_ohlcv:
        for ctx_tf, ctx_candles in context_ohlcv.items():
            human_parts.append(f"\nContext Timeframe: {ctx_tf} (Last 20 candles):\n{json.dumps(ctx_candles[-20:], indent=2, default=str)}")

    human_parts.append("\nCurrently Open Positions:\n" + "\n".join(pos_lines))
    if sig_lines:
        human_parts.append("\nRecent Signal History (newest first):\n" + "\n".join(sig_lines))
    if news_context:
        human_parts.append(f"\n{news_context}")
    if trade_history_context:
        human_parts.append(f"\n{trade_history_context}")
    human_parts.append("\nProvide the market context JSON.")

    messages = [
        SystemMessage(content=_MARKET_ANALYSIS_SYSTEM),
        HumanMessage(content="\n".join(human_parts)),
    ]
    return await _call_llm_for_role(llm, messages, "market_analysis")


# ── Role: Chart Vision ─────────────────────────────────────────────────────────

async def _run_chart_vision(
    llm: BaseChatModel,
    symbol: str,
    timeframe: str,
    chart_image_b64: str,
    market_context: dict,
) -> LLMRoleResult:
    """LLM Role 2: Analyze chart image and identify visual patterns."""
    system = """You are a technical chart analyst. Identify visual price patterns from the chart image.
Return ONLY strictly valid JSON:
{
  "chart_pattern": "<pattern name, e.g. double_top | head_shoulders | channel | none>",
  "pattern_direction": "bullish | bearish | neutral",
  "chart_notes": "<2-3 sentence description of what you see in the chart>"
}"""

    human_text = (
        f"Symbol: {symbol} | Timeframe: {timeframe}\n"
        f"Market Context: {json.dumps(market_context, indent=2)}\n"
        "Analyze this chart and return the visual pattern JSON."
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=[
            {"type": "text", "text": human_text},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{chart_image_b64}"}},
        ]),
    ]
    return await _call_llm_for_role(llm, messages, "chart_vision")


# ── Role: Execution Decision ───────────────────────────────────────────────────

async def _run_execution_decision(
    llm: BaseChatModel,
    symbol: str,
    timeframe: str,
    current_price: float,
    market_context: dict,
    visual_pattern: dict | None,
    open_positions: list[dict],
    recent_signals: list[dict],
    system_prompt_override: str | None,
) -> LLMRoleResult:
    """LLM Role 3: Make final trade execution decision given all context."""
    system = system_prompt_override or _EXECUTION_SYSTEM

    pos_lines = [
        f"  - {p.get('symbol', symbol)} {p.get('direction','?')} vol={p.get('volume','?')} profit={p.get('profit','?')}"
        for p in (open_positions or [])
    ] or ["  None"]

    human_parts = [
        f"Symbol: {symbol}\nTimeframe: {timeframe}\nCurrent Price: {current_price}",
        f"\nMarket Analysis:\n{json.dumps(market_context, indent=2)}",
    ]
    if visual_pattern:
        human_parts.append(f"\nChart Pattern Analysis:\n{json.dumps(visual_pattern, indent=2)}")
    human_parts.append("\nCurrently Open Positions:\n" + "\n".join(pos_lines))
    if recent_signals:
        sig_lines = [
            f"  - {s.get('symbol',symbol)} {s.get('signal','?')} conf={s.get('confidence','?')} | {s.get('rationale','')[:80]}"
            for s in recent_signals
        ]
        human_parts.append("\nRecent Signal History:\n" + "\n".join(sig_lines))
    human_parts.append("\nProvide the trading signal JSON.")

    messages = [
        SystemMessage(content=system),
        HumanMessage(content="\n".join(human_parts)),
    ]
    return await _call_llm_for_role(llm, messages, "execution_decision")


# ── Maintenance Roles ──────────────────────────────────────────────────────────

async def _run_maintenance_technical(
    llm: BaseChatModel,
    symbol: str,
    timeframe: str,
    ohlcv: list[dict],
    indicators: dict,
    position: dict,
    strategy_params: dict,
) -> LLMRoleResult:
    """Role 1: Technical analysis of the existing position."""
    human = "\n".join([
        f"Symbol: {symbol} | Timeframe: {timeframe}",
        f"\nPosition State:\n{json.dumps(position, indent=2, default=str)}",
        f"\nIndicators:\n{json.dumps(indicators, indent=2)}",
        f"\nStrategy Params:\n{json.dumps(strategy_params, indent=2)}",
        f"\nLast 20 OHLCV candles (oldest → newest):\n{json.dumps(ohlcv[-20:], indent=2, default=str)}",
        "\nProvide the technical analysis JSON.",
    ])
    messages = [
        SystemMessage(content=_MAINTENANCE_TECHNICAL_SYSTEM),
        HumanMessage(content=human),
    ]
    return await _call_llm_for_role(llm, messages, "maintenance_technical")


async def _run_maintenance_sentiment(
    llm: BaseChatModel,
    symbol: str,
    news_context: str | None,
    trade_history_context: str | None,
) -> LLMRoleResult:
    """Role 2: News sentiment analysis for the symbol."""
    human_parts = [f"Symbol: {symbol}"]
    if news_context:
        human_parts.append(f"\nUpcoming News & Events:\n{news_context}")
    else:
        human_parts.append("\nNo news data available — assess NEUTRAL sentiment.")
    if trade_history_context:
        human_parts.append(f"\nRecent Trade History:\n{trade_history_context}")
    human_parts.append("\nProvide the sentiment analysis JSON.")
    messages = [
        SystemMessage(content=_MAINTENANCE_SENTIMENT_SYSTEM),
        HumanMessage(content="\n".join(human_parts)),
    ]
    return await _call_llm_for_role(llm, messages, "maintenance_sentiment")


async def _run_maintenance_decision(
    llm: BaseChatModel,
    symbol: str,
    position: dict,
    technical_output: dict,
    sentiment_output: dict,
    strategy_params: dict,
) -> LLMRoleResult:
    """Role 3: Final hold/close/modify decision."""
    human = "\n".join([
        f"Symbol: {symbol}",
        f"\nPosition State:\n{json.dumps(position, indent=2, default=str)}",
        f"\nStrategy Constraints:\n{json.dumps(strategy_params, indent=2)}",
        f"\nTechnical Analysis:\n{json.dumps(technical_output, indent=2, default=str)}",
        f"\nSentiment Analysis:\n{json.dumps(sentiment_output, indent=2, default=str)}",
        "\nProvide the maintenance decision JSON.",
    ])
    messages = [
        SystemMessage(content=_MAINTENANCE_DECISION_SYSTEM),
        HumanMessage(content=human),
    ]
    return await _call_llm_for_role(llm, messages, "maintenance_decision")


# ── News analysis gate ────────────────────────────────────────────────────────

_NEWS_ANALYSIS_SYSTEM = """\
You are a forex news impact analyst. Given upcoming High-impact economic events,
predict the likely short-term price direction for the specified symbol.

Respond with valid JSON only — no markdown fences:
{"signal": "BUY" | "SELL" | "HOLD", "reasoning": "<1-2 sentences>"}

Rules:
- BUY  = news likely to push price UP (e.g. strong jobs data for USD → EURUSD falls → SELL EUR, BUY USD)
- SELL = news likely to push price DOWN
- HOLD = news impact unclear / mixed / not directly affecting this symbol
- When in doubt, respond HOLD.
"""


async def analyze_news_impact(
    events: list[dict[str, Any]],
    symbol: str,
    llm: "BaseChatModel | None" = None,
) -> NewsAnalysisResult:
    """Ask a lightweight LLM to predict price direction from upcoming High-impact news.

    Returns NewsAnalysisResult(signal="HOLD") on any error — never raises.
    Used as a pre-execution gate in the trading pipeline.
    """
    _llm = llm or _build_llm()

    now_utc = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    event_lines = []
    for e in events:
        mins_until = int(
            (__import__("datetime").datetime.fromisoformat(e["time"]) - now_utc).total_seconds() / 60
        )
        line = f"  - {e['currency']} | {e['title']} | in {mins_until} min"
        if e.get("forecast"):
            line += f" | Forecast: {e['forecast']}"
        if e.get("previous"):
            line += f" | Previous: {e['previous']}"
        event_lines.append(line)

    human = (
        f"Symbol: {symbol}\n"
        f"Upcoming High-Impact Events:\n" + "\n".join(event_lines) + "\n\n"
        f"What is the likely short-term price direction for {symbol}?"
    )

    try:
        result = await _call_llm_for_role(
            _llm,
            [SystemMessage(content=_NEWS_ANALYSIS_SYSTEM), HumanMessage(content=human)],
            "news_analysis",
        )
        raw = result.content if isinstance(result.content, dict) else {}
        signal = str(raw.get("signal", "HOLD")).upper()
        if signal not in ("BUY", "SELL", "HOLD"):
            signal = "HOLD"
        return NewsAnalysisResult(
            signal=signal,
            reasoning=str(raw.get("reasoning", "")),
            role_result=result,
        )
    except Exception as exc:
        logger.warning("News analysis LLM failed for %s: %s", symbol, exc)
        return NewsAnalysisResult(signal="HOLD", reasoning=f"error: {exc}")


# ── Public API ────────────────────────────────────────────────────────────────

async def analyze_market(
    symbol: str,
    timeframe: str,
    current_price: float,
    indicators: dict[str, Any],
    ohlcv: list[dict[str, Any]],
    chart_analysis: str | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    recent_signals: list[dict[str, Any]] | None = None,
    news_context: str | None = None,
    trade_history_context: str | None = None,
    system_prompt_override: str | None = None,
    llm_override: BaseChatModel | None = None,
    # Per-role LLM overrides
    market_analysis_llm: BaseChatModel | None = None,
    chart_vision_llm: BaseChatModel | None = None,
    execution_decision_llm: BaseChatModel | None = None,
    indicator_agent_llm: BaseChatModel | None = None,
    context_ohlcv: dict[str, list[dict]] | None = None,
) -> LLMAnalysisResult:
    """Run 3-role LLM analysis pipeline: market_analysis → chart_vision → execution_decision.

    Each role makes an independent LLM call and records token usage.
    llm_override applies to ALL roles if role-specific overrides are not set (legacy compat).
    When settings.enable_agent_pipeline=True, routes to the 4-agent parallel pipeline instead.
    """
    default_llm = llm_override or _build_llm()

    if settings.enable_agent_pipeline:
        return await run_agent_pipeline(
            symbol=symbol,
            timeframe=timeframe,
            current_price=current_price,
            ohlcv=ohlcv,
            indicators=indicators,
            chart_image_b64=chart_analysis,
            news_context=news_context,
            open_positions=open_positions,
            trade_history=recent_signals,
            trade_history_context=trade_history_context,
            context_ohlcv=context_ohlcv,
            market_analysis_llm=market_analysis_llm or default_llm,
            chart_vision_llm=chart_vision_llm or default_llm,
            execution_decision_llm=execution_decision_llm or default_llm,
            indicator_agent_llm=indicator_agent_llm or default_llm,
        )
    ma_llm  = market_analysis_llm    or default_llm
    cv_llm  = chart_vision_llm       or default_llm
    ed_llm  = execution_decision_llm or default_llm

    logger.info(
        "Analyzing market | symbol=%s timeframe=%s price=%s | providers: ma=%s cv=%s ed=%s",
        symbol, timeframe, current_price,
        _provider_from_llm(ma_llm), _provider_from_llm(cv_llm), _provider_from_llm(ed_llm),
    )

    # ── Role 1: Market Analysis ───────────────────────────────────────────────
    ma_result = await _run_market_analysis(
        ma_llm, symbol, timeframe, current_price,
        indicators, ohlcv, open_positions or [], recent_signals or [],
        news_context, trade_history_context, context_ohlcv,
    )
    market_context = ma_result.content if isinstance(ma_result.content, dict) else {}

    # ── Role 2: Chart Vision (optional) ──────────────────────────────────────
    cv_result: LLMRoleResult | None = None
    visual_pattern: dict | None = None
    if chart_analysis:
        # chart_analysis is treated as base64 image if it's long and doesn't start with newline.
        # Otherwise treat as pre-analyzed text for backward compatibility.
        if len(chart_analysis) > 200 and not chart_analysis.startswith("\n"):
            cv_result = await _run_chart_vision(
                cv_llm, symbol, timeframe, chart_analysis, market_context
            )
            visual_pattern = cv_result.content if isinstance(cv_result.content, dict) else None
        else:
            market_context["chart_analysis_text"] = chart_analysis

    # ── Role 3: Execution Decision ────────────────────────────────────────────
    ed_result = await _run_execution_decision(
        ed_llm, symbol, timeframe, current_price,
        market_context, visual_pattern,
        open_positions or [], recent_signals or [],
        system_prompt_override,
    )

    raw = ed_result.content if isinstance(ed_result.content, dict) else {}
    raw = _normalize_raw(raw, timeframe=timeframe, current_price=current_price)
    signal = TradingSignal(**raw)

    # Confidence gate — threshold nudged by the research loop's per-symbol trust score
    gate_threshold = effective_confidence_threshold(symbol, settings.llm_confidence_threshold)
    if signal.confidence < gate_threshold:
        logger.info(
            "Signal downgraded to HOLD — confidence %.2f below effective threshold %.2f "
            "(base=%.2f) | symbol=%s",
            signal.confidence, gate_threshold, settings.llm_confidence_threshold, symbol,
        )
        signal.action = "HOLD"

    logger.info(
        "Signal result | symbol=%s action=%s confidence=%.2f timeframe=%s",
        symbol, signal.action, signal.confidence, signal.timeframe,
    )
    return LLMAnalysisResult(
        signal=signal,
        market_analysis=ma_result,
        chart_vision=cv_result,
        execution_decision=ed_result,
    )


# ── Public: Maintenance Pipeline ───────────────────────────────────────────────

async def review_position(
    symbol: str,
    timeframe: str,
    ohlcv: list[dict],
    indicators: dict,
    position: dict,
    strategy_params: dict,
    news_context: str | None = None,
    trade_history_context: str | None = None,
    *,
    technical_llm: BaseChatModel | None = None,
    sentiment_llm: BaseChatModel | None = None,
    decision_llm: BaseChatModel | None = None,
) -> MaintenanceResult:
    """3-role LLM maintenance pipeline: technical → sentiment → decision.

    Args:
        symbol: Instrument symbol (e.g. 'EURUSD').
        timeframe: Strategy timeframe (e.g. 'H1').
        ohlcv: List of OHLCV candle dicts (last 20 sufficient).
        indicators: Dict of computed indicator values.
        position: Dict with position state (ticket, direction, entry_price,
                  current_price, current_sl, current_tp, unrealized_pnl,
                  volume, duration_hours).
        strategy_params: Dict with sl_pips, tp_pips, risk_pct, max_lot_size.
        news_context: Optional formatted news string from MarketContext.
        trade_history_context: Optional formatted trade history string.
        technical_llm: Override LLM for role 1. Uses default provider if None.
        sentiment_llm: Override LLM for role 2. Uses default provider if None.
        decision_llm: Override LLM for role 3. Uses default provider if None.

    Returns:
        MaintenanceResult with parsed decision and all 3 role results.
    """
    llm_technical = technical_llm or _build_llm()
    llm_sentiment = sentiment_llm or _build_llm()
    llm_decision = decision_llm or _build_llm()

    # Role 1: Technical analysis
    tech_result = await _run_maintenance_technical(
        llm_technical, symbol, timeframe, ohlcv, indicators, position, strategy_params
    )

    # Role 2: Sentiment analysis
    sent_result = await _run_maintenance_sentiment(
        llm_sentiment, symbol, news_context, trade_history_context
    )

    # Role 3: Final decision (receives outputs of roles 1 and 2)
    tech_output = tech_result.content if isinstance(tech_result.content, dict) else {}
    sent_output = sent_result.content if isinstance(sent_result.content, dict) else {}
    dec_result = await _run_maintenance_decision(
        llm_decision, symbol, position, tech_output, sent_output, strategy_params
    )

    # Parse MaintenanceDecision from role 3 output
    raw = dec_result.content if isinstance(dec_result.content, dict) else {}
    raw.setdefault("action", "HOLD")
    raw.setdefault("confidence", 0.0)
    raw.setdefault("rationale", "No rationale provided.")
    if isinstance(raw.get("action"), str):
        raw["action"] = raw["action"].upper()

    try:
        decision = MaintenanceDecision(**raw)
    except Exception as exc:
        logger.warning("MaintenanceDecision parse failed (%s) — defaulting to HOLD: %s", exc, raw)
        decision = MaintenanceDecision(
            action="HOLD", confidence=0.0, rationale=f"Parse error: {exc}"
        )

    # Confidence gate: downgrade to HOLD if below threshold (nudged by symbol trust score)
    gate_threshold = effective_confidence_threshold(symbol, settings.llm_confidence_threshold)
    if decision.action != "HOLD" and decision.confidence < gate_threshold:
        logger.info(
            "Maintenance decision downgraded HOLD (confidence %.2f < effective threshold %.2f, base=%.2f)",
            decision.confidence, gate_threshold, settings.llm_confidence_threshold,
        )
        decision = MaintenanceDecision(
            action="HOLD",
            confidence=decision.confidence,
            rationale=f"Confidence {decision.confidence:.2f} below threshold — HOLD",
        )

    return MaintenanceResult(
        decision=decision,
        technical_analysis=tech_result,
        sentiment_analysis=sent_result,
        maintenance_decision=dec_result,
    )


# ── Public: Multi-Agent Pipeline ───────────────────────────────────────────────

async def run_agent_pipeline(
    symbol: str,
    timeframe: str,
    current_price: float,
    ohlcv: list[dict[str, Any]],
    indicators: dict[str, Any] | None = None,
    chart_image_b64: str | None = None,
    news_context: str | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    trade_history: list[dict[str, Any]] | None = None,
    trade_history_context: str | None = None,
    context_ohlcv: dict[str, list[dict]] | None = None,
    *,
    market_analysis_llm: BaseChatModel | None = None,
    chart_vision_llm: BaseChatModel | None = None,
    execution_decision_llm: BaseChatModel | None = None,
    indicator_agent_llm: BaseChatModel | None = None,
) -> LLMAnalysisResult:
    """Entry point for the 4-agent parallel pipeline.

    Pipeline: market_analysis (sequential) → [indicator, pattern, trend] (parallel) → decision.
    Called when settings.enable_agent_pipeline=True.

    Returns LLMAnalysisResult for backward-compatible interface with analyze_market().
    The execution_decision LLMRoleResult carries the final_signal as its content.
    """
    import time

    from ai.agent_pipeline import AgentPipelineState, build_pipeline
    from services.technical_indicators import (
        compute_indicators,
        fit_trendlines,
        render_trendline_chart,
    )

    t0 = time.monotonic()
    default_llm = _build_llm()
    ma_llm = market_analysis_llm or default_llm
    cv_llm = chart_vision_llm or default_llm
    ed_llm = execution_decision_llm or default_llm
    ia_llm = indicator_agent_llm or _build_llm(
        model=settings.indicator_agent_model or None
    ) if settings.indicator_agent_model else default_llm

    logger.info(
        "Agent pipeline start | symbol=%s timeframe=%s price=%s",
        symbol, timeframe, current_price,
    )

    # Compute indicators from OHLCV if not provided
    computed_indicators: dict = indicators or {}
    if not computed_indicators and len(ohlcv) >= 50:
        try:
            computed_indicators = compute_indicators(ohlcv)
        except Exception as exc:
            logger.warning("Indicator computation failed: %s — using empty dict", exc)

    # Render trendline chart if base candlestick chart is provided
    trendline_chart_b64: str | None = None
    if chart_image_b64 and len(ohlcv) >= 50:
        try:
            import numpy as np
            bars = ohlcv[-50:]
            high = np.array([c["high"] for c in bars])
            low = np.array([c["low"] for c in bars])
            close = np.array([c["close"] for c in bars])
            s_slope, s_int, r_slope, r_int = fit_trendlines(high, low, close)
            trendline_chart_b64 = render_trendline_chart(ohlcv, s_slope, s_int, r_slope, r_int) or None
        except Exception as exc:
            logger.warning("Trendline chart generation failed: %s", exc)

    # Build and run the LangGraph pipeline
    pipeline = build_pipeline(ma_llm, ia_llm, cv_llm, ed_llm, settings)
    initial_state: AgentPipelineState = {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": current_price,
        "ohlcv": ohlcv,
        "indicators": computed_indicators,
        "chart_image_b64": chart_image_b64,
        "trendline_chart_b64": trendline_chart_b64,
        "news_context": news_context,
        "open_positions": open_positions,
        "trade_history": trade_history,
        "trade_history_context": trade_history_context,
        "context_ohlcv": context_ohlcv,
        "market_context": None,
        "indicator_report": None,
        "pattern_report": None,
        "trend_report": None,
        "final_signal": None,
        "error": None,
        "market_analysis_tokens": None,
        "indicator_tokens": None,
        "pattern_tokens": None,
        "trend_tokens": None,
        "decision_tokens": None,
        "market_analysis_prompt": None,
        "indicator_prompt": None,
        "pattern_prompt": None,
        "trend_prompt": None,
        "decision_prompt": None,
        "vote_summary": None,
    }
    final_state = await pipeline.ainvoke(initial_state)

    duration_ms = int((time.monotonic() - t0) * 1000)
    final_signal: dict = final_state.get("final_signal") or {
        "signal": "HOLD", "confidence": 0.0, "justification": "pipeline_returned_no_signal",
    }
    logger.info(
        "Agent pipeline complete | symbol=%s signal=%s confidence=%s duration=%dms",
        symbol, final_signal.get("signal"), final_signal.get("confidence"), duration_ms,
    )

    # Map pipeline output → LLMAnalysisResult
    action = final_signal.get("signal", "HOLD")
    raw = {
        "action": action,
        "entry": final_signal.get("suggested_entry", current_price) or current_price,
        "stop_loss": float(final_signal.get("stop_loss") or 0.0),
        "take_profit": float(final_signal.get("take_profit") or 0.0),
        "confidence": float(final_signal.get("confidence", 0.0)),
        "rationale": final_signal.get("justification", ""),
        "timeframe": timeframe,
        "expiry_multiplier": float(final_signal.get("expiry_multiplier") or 1.0),
    }
    raw = _normalize_raw(raw, timeframe=timeframe, current_price=current_price)
    signal = TradingSignal(**raw)

    gate_threshold = effective_confidence_threshold(symbol, settings.llm_confidence_threshold)
    if signal.confidence < gate_threshold:
        logger.info(
            "Agent pipeline signal downgraded HOLD — confidence %.2f below effective threshold %.2f "
            "(base=%.2f)",
            signal.confidence, gate_threshold, settings.llm_confidence_threshold,
        )
        signal.action = "HOLD"

    def _role_result_from_tokens(
        tokens: dict | None,
        llm: BaseChatModel,
        content: Any,
        prompt: Any = None,
    ) -> LLMRoleResult:
        t = tokens or {}
        return LLMRoleResult(
            content=content,
            input_tokens=t.get("input_tokens"),
            output_tokens=t.get("output_tokens"),
            total_tokens=t.get("total_tokens"),
            model=t.get("model") or _model_name_from_llm(llm),
            provider=t.get("provider") or _provider_from_llm(llm),
            duration_ms=t.get("duration_ms") or duration_ms,
            raw_text="",
            prompt=prompt or None,
        )

    def _optional_role_result(
        tokens: dict | None,
        content: Any,
        prompt: Any = None,
    ) -> LLMRoleResult | None:
        if tokens is None:
            return None
        return LLMRoleResult(
            content=content,
            input_tokens=tokens.get("input_tokens"),
            output_tokens=tokens.get("output_tokens"),
            total_tokens=tokens.get("total_tokens"),
            model=tokens.get("model", "unknown"),
            provider=tokens.get("provider", "unknown"),
            duration_ms=tokens.get("duration_ms", 0),
            raw_text="",
            prompt=prompt or None,
        )

    return LLMAnalysisResult(
        signal=signal,
        market_analysis=_role_result_from_tokens(
            final_state.get("market_analysis_tokens"), ma_llm,
            final_state.get("market_context") or {},
            final_state.get("market_analysis_prompt") or "",
        ),
        chart_vision=None,
        execution_decision=_role_result_from_tokens(
            final_state.get("decision_tokens"), ed_llm,
            final_signal,
            final_state.get("decision_prompt") or "",
        ),
        indicator_agent=_optional_role_result(
            final_state.get("indicator_tokens"),
            final_state.get("indicator_report"),
            final_state.get("indicator_prompt") or "",
        ),
        pattern_agent=_optional_role_result(
            final_state.get("pattern_tokens"),
            final_state.get("pattern_report"),
            final_state.get("pattern_prompt") or "",
        ),
        trend_agent=_optional_role_result(
            final_state.get("trend_tokens"),
            final_state.get("trend_report"),
            final_state.get("trend_prompt") or "",
        ),
        trendline_chart_b64=trendline_chart_b64,
        vote_summary=final_state.get("vote_summary"),
    )
