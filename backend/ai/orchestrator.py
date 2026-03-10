"""LangChain Orchestrator — all LLM interactions go through here.

Never call OpenAI / Gemini / Anthropic APIs directly from routes or services.
The signal pipeline: market data → market_analysis_llm → chart_vision_llm → execution_decision_llm → TradingSignal.
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from core.config import settings

logger = logging.getLogger(__name__)


# ── Signal schema ─────────────────────────────────────────────────────────────

_VALID_ACTIONS = frozenset({"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "HOLD"})


class TradingSignal(BaseModel):
    action: str = Field(..., description="BUY | SELL | BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | HOLD")
    entry: float = Field(..., description="Recommended entry price")
    stop_loss: float = Field(..., description="Stop loss price")
    take_profit: float = Field(..., description="Take profit price")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Signal confidence 0-1")
    rationale: str = Field(..., description="Brief explanation of the signal")
    timeframe: str = Field(..., description="Analysis timeframe e.g. M15")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v.upper() not in _VALID_ACTIONS:
            raise ValueError(f"action must be one of {sorted(_VALID_ACTIONS)}")
        return v.upper()


@dataclass
class LLMRoleResult:
    """Result from a single LLM role call, including token usage."""
    content: Any                          # parsed dict or str output
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model: str
    provider: str
    duration_ms: int
    raw_text: str = ""                    # raw text response before parsing


@dataclass
class LLMAnalysisResult:
    """Combined result from all 3 LLM role calls."""
    signal: TradingSignal
    market_analysis: LLMRoleResult
    chart_vision: LLMRoleResult | None    # None if no chart image provided
    execution_decision: LLMRoleResult


_VALID_MAINTENANCE_ACTIONS = frozenset({"HOLD", "CLOSE", "MODIFY"})


class MaintenanceDecision(BaseModel):
    """LLM output from the maintenance_decision role."""
    action: str = Field(..., description="HOLD | CLOSE | MODIFY")
    new_sl: float | None = Field(None, description="New stop loss price (MODIFY only)")
    new_tp: float | None = Field(None, description="New take profit price (MODIFY only)")
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., description="1-2 sentence explanation")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v.upper() not in _VALID_MAINTENANCE_ACTIONS:
            raise ValueError(f"action must be one of {sorted(_VALID_MAINTENANCE_ACTIONS)}")
        return v.upper()


@dataclass
class MaintenanceResult:
    """Combined result from the 3-role maintenance pipeline."""
    decision: MaintenanceDecision
    technical_analysis: LLMRoleResult
    sentiment_analysis: LLMRoleResult
    maintenance_decision: LLMRoleResult


# ── LLM factory ───────────────────────────────────────────────────────────────

def _build_llm(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseChatModel:
    """Build a LangChain chat model from provider config or env-var settings."""
    resolved_provider = provider or settings.llm_provider

    if resolved_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "gpt-4o",
            api_key=api_key or settings.openai_api_key,
            temperature=0,
        )

    if resolved_provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model or settings.gemini_model,
            google_api_key=api_key or settings.gemini_api_key,
            temperature=0,
        )

    if resolved_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-sonnet-4-6",
            api_key=api_key or settings.anthropic_api_key,
            temperature=0,
        )

    raise ValueError(f"Unknown llm_provider: {resolved_provider!r}")


def _provider_from_llm(llm: BaseChatModel) -> str:
    """Derive short provider name from LangChain model class."""
    mod = type(llm).__module__
    if "openai" in mod:
        return "openai"
    if "google" in mod or "gemini" in mod:
        return "google"
    if "anthropic" in mod:
        return "anthropic"
    return "unknown"


def _model_name_from_llm(llm: BaseChatModel) -> str:
    """Extract model name string from LangChain model instance."""
    return getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"


def _extract_tokens(ai_msg: Any, provider: str) -> tuple[int | None, int | None, int | None]:
    """Extract (input_tokens, output_tokens, total_tokens) from LangChain AIMessage.

    Tries the standardized LangChain v0.2+ usage_metadata dict first (works across all
    providers), then falls back to provider-specific response_metadata fields.
    """
    try:
        # ── Standard LangChain v0.2+ path ─────────────────────────────────────
        # AIMessage.usage_metadata is a dict: {input_tokens, output_tokens, total_tokens}
        meta = getattr(ai_msg, "usage_metadata", None)
        if isinstance(meta, dict) and "input_tokens" in meta:
            inp = meta.get("input_tokens")
            out = meta.get("output_tokens")
            total = meta.get("total_tokens") or (
                (inp or 0) + (out or 0) if inp is not None and out is not None else None
            )
            return inp, out, total

        # ── Provider-specific fallbacks ────────────────────────────────────────
        if provider == "openai":
            usage = ai_msg.response_metadata.get("token_usage", {})
            inp = usage.get("prompt_tokens")
            out = usage.get("completion_tokens")
            total = usage.get("total_tokens")
            return inp, out, total

        if provider == "anthropic":
            usage = ai_msg.response_metadata.get("usage", {})
            inp = usage.get("input_tokens")
            out = usage.get("output_tokens")
            total = (inp or 0) + (out or 0) if inp is not None and out is not None else None
            return inp, out, total

        if provider == "google":
            # Older langchain-google-genai: usage data nested in response_metadata
            rm = getattr(ai_msg, "response_metadata", {}) or {}
            usage = rm.get("usage_metadata") or rm.get("usageMetadata") or {}
            if isinstance(usage, dict):
                inp = usage.get("prompt_token_count") or usage.get("promptTokenCount")
                out = usage.get("candidates_token_count") or usage.get("candidatesTokenCount")
                total = usage.get("total_token_count") or usage.get("totalTokenCount")
                return inp, out, total

    except Exception as exc:
        logger.debug("Could not extract token usage: %s", exc)
    return None, None, None


# ── Per-role LLM caller ────────────────────────────────────────────────────────

async def _call_llm_for_role(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    role: str,
) -> LLMRoleResult:
    """Invoke an LLM directly (not via chain) and return result with token usage."""
    provider = _provider_from_llm(llm)
    model = _model_name_from_llm(llm)
    t0 = time.monotonic()

    ai_msg = await llm.ainvoke(messages)
    duration_ms = int((time.monotonic() - t0) * 1000)

    raw_text = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
    inp, out, total = _extract_tokens(ai_msg, provider)

    # Parse JSON from the text response
    try:
        # Strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        content = json.loads(text)
    except Exception:
        content = raw_text

    logger.info(
        "LLM role=%s provider=%s model=%s input=%s output=%s total=%s duration=%dms",
        role, provider, model, inp, out, total, duration_ms,
    )
    return LLMRoleResult(
        content=content,
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        model=model,
        provider=provider,
        duration_ms=duration_ms,
        raw_text=raw_text,
    )


# ── Normaliser (shared) ────────────────────────────────────────────────────────

def _normalize_raw(raw: dict, *, timeframe: str, current_price: float) -> dict:
    """Map alternative LLM field names to the canonical TradingSignal schema."""
    out = dict(raw)

    if "action" not in out:
        for alias in ("signal", "side", "direction", "trade_action"):
            if alias in out:
                out["action"] = out.pop(alias)
                break

    if "rationale" not in out:
        for alias in ("explanation", "reason", "reasoning", "summary", "note"):
            if alias in out:
                out["rationale"] = out.pop(alias)
                break

    if "timeframe" not in out:
        out["timeframe"] = timeframe

    out.setdefault("action", "HOLD")
    out.setdefault("entry", current_price)
    out.setdefault("stop_loss", 0.0)
    out.setdefault("take_profit", 0.0)
    out.setdefault("confidence", 0.0)
    out.setdefault("rationale", "No rationale provided by model.")

    if isinstance(out.get("action"), str):
        out["action"] = out["action"].upper()

    logger.debug("LLM raw → normalised: %s", out)
    return out


# ── System prompts ─────────────────────────────────────────────────────────────

_MARKET_ANALYSIS_SYSTEM = """You are a professional forex market analyst.
Analyze the market data and return ONLY strictly valid JSON:
{{
  "trend": "bullish | bearish | ranging",
  "trend_strength": <float 0.0-1.0>,
  "key_support": <float>,
  "key_resistance": <float>,
  "volatility": "low | medium | high",
  "context_notes": "<2-3 sentence analysis of current market conditions>"
}}"""

_EXECUTION_SYSTEM = """You are a professional forex trader making execution decisions.
Based on the market analysis and position context provided, return ONLY strictly valid JSON.
Use EXACTLY these field names:
{{
  "action": "BUY | SELL | BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | HOLD",
  "entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "confidence": <float 0.0-1.0>,
  "rationale": "<brief 1-2 sentence explanation>",
  "timeframe": "<e.g. M15>"
}}

Order type guidance (IMPORTANT — pick the right action):
- BUY / SELL: market order — use ONLY when price is already at your optimal entry level.
- BUY_LIMIT: pending buy below current price — expect retracement DOWN to 'entry' then reversal up.
- SELL_LIMIT: pending sell above current price — expect retracement UP to 'entry' then reversal down.
- BUY_STOP: pending buy above current price — buy on upside BREAKOUT through 'entry'.
- SELL_STOP: pending sell below current price — sell on downside BREAKDOWN through 'entry'.
- HOLD: no trade opportunity.

Rules:
- Signal BUY or SELL only when multiple indicators confirm the same direction.
- Signal HOLD when uncertain or risk/reward is unfavorable.
- Check open positions before signaling. Avoid doubling same direction unless confidence > 0.90.
- Never open opposing positions simultaneously."""

_MAINTENANCE_TECHNICAL_SYSTEM = """You are a professional forex technical analyst reviewing an existing open position.
Analyze the position's technical merit given current market conditions.
Return ONLY strictly valid JSON:
{
  "trend": "uptrend | downtrend | ranging",
  "trend_strength": <float 0.0-1.0>,
  "key_support": <float>,
  "key_resistance": <float>,
  "position_alignment": "aligned | misaligned | neutral",
  "technical_score": <float -1.0 to 1.0>,
  "notes": "<2-3 sentences on technical outlook for this position>"
}"""

_MAINTENANCE_SENTIMENT_SYSTEM = """You are a professional forex market analyst assessing news sentiment impact.
Given upcoming economic events and recent news, assess directional sentiment for the symbol.
Return ONLY strictly valid JSON:
{
  "sentiment_direction": "BULLISH | BEARISH | NEUTRAL",
  "event_risk": "HIGH | MEDIUM | LOW",
  "key_events": ["<event 1>", "<event 2>"],
  "sentiment_score": <float -1.0 to 1.0>,
  "notes": "<2 sentences on news impact for this symbol>"
}"""

_MAINTENANCE_DECISION_SYSTEM = """You are a professional forex risk manager reviewing an open position.
Given the technical analysis, sentiment analysis, and the position's current state,
recommend whether to HOLD, CLOSE, or MODIFY the position's SL/TP.

You MUST adhere to the strategy constraints provided. When suggesting MODIFY:
- new_sl and new_tp must respect the minimum SL distance (sl_pips)
- For profitable positions: new_sl must move toward profit (trailing logic)
- new_tp must maintain at least 1:1 R:R relative to new_sl distance from entry

Return ONLY strictly valid JSON:
{
  "action": "HOLD | CLOSE | MODIFY",
  "new_sl": <float or null>,
  "new_tp": <float or null>,
  "confidence": <float 0.0-1.0>,
  "rationale": "<1-2 sentence explanation>"
}

Rules:
- Signal CLOSE if position is strongly misaligned with current technical + sentiment.
- Signal MODIFY only when SL/TP improvements are clearly justified.
- Signal HOLD when uncertain or when the position is performing as expected.
- NEVER suggest modifications that increase risk beyond the strategy's risk_pct."""


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
    regime_context: str | None,
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
    if regime_context:
        human_parts.append(f"\nMarket Regime (HMM):\n{regime_context}")
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
    regime_context: str | None = None,
    system_prompt_override: str | None = None,
    llm_override: BaseChatModel | None = None,
    # Per-role LLM overrides
    market_analysis_llm: BaseChatModel | None = None,
    chart_vision_llm: BaseChatModel | None = None,
    execution_decision_llm: BaseChatModel | None = None,
    context_ohlcv: dict[str, list[dict]] | None = None,
) -> LLMAnalysisResult:
    """Run 3-role LLM analysis pipeline: market_analysis → chart_vision → execution_decision.

    Each role makes an independent LLM call and records token usage.
    llm_override applies to ALL roles if role-specific overrides are not set (legacy compat).
    """
    default_llm = llm_override or _build_llm()
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
        news_context, trade_history_context, regime_context, context_ohlcv,
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

    # Confidence gate
    if signal.confidence < settings.llm_confidence_threshold:
        logger.info(
            "Signal downgraded to HOLD — confidence %.2f below threshold %.2f | symbol=%s",
            signal.confidence, settings.llm_confidence_threshold, symbol,
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

    # Confidence gate: downgrade to HOLD if below threshold
    if decision.action != "HOLD" and decision.confidence < settings.llm_confidence_threshold:
        logger.info(
            "Maintenance decision downgraded HOLD (confidence %.2f < threshold %.2f)",
            decision.confidence, settings.llm_confidence_threshold,
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
