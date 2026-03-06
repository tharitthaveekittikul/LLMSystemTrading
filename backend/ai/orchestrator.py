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

class TradingSignal(BaseModel):
    action: str = Field(..., description="BUY | SELL | HOLD")
    entry: float = Field(..., description="Recommended entry price")
    stop_loss: float = Field(..., description="Stop loss price")
    take_profit: float = Field(..., description="Take profit price")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Signal confidence 0-1")
    rationale: str = Field(..., description="Brief explanation of the signal")
    timeframe: str = Field(..., description="Analysis timeframe e.g. M15")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v.upper() not in {"BUY", "SELL", "HOLD"}:
            raise ValueError("action must be BUY, SELL, or HOLD")
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
    """Extract (input_tokens, output_tokens, total_tokens) from LangChain AIMessage."""
    try:
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
            meta = getattr(ai_msg, "usage_metadata", None)
            if meta is None:
                return None, None, None
            inp = getattr(meta, "prompt_token_count", None)
            out = getattr(meta, "candidates_token_count", None)
            total = getattr(meta, "total_token_count", None)
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
  "action": "BUY | SELL | HOLD",
  "entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "confidence": <float 0.0-1.0>,
  "rationale": "<brief 1-2 sentence explanation>",
  "timeframe": "<e.g. M15>"
}}

Rules:
- Signal BUY or SELL only when multiple indicators confirm the same direction.
- Signal HOLD when uncertain or risk/reward is unfavorable.
- Check open positions before signaling. Avoid doubling same direction unless confidence > 0.90.
- Never open opposing positions simultaneously."""


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
        f"Symbol: {symbol}\nTimeframe: {timeframe}\nCurrent Price: {current_price}",
        f"\nIndicators:\n{json.dumps(indicators, indent=2)}",
    ]
    if regime_context:
        human_parts.append(f"\nMarket Regime (HMM):\n{regime_context}")
    human_parts.append(f"\nLast 20 OHLCV candles (oldest → newest):\n{json.dumps(ohlcv[-20:], indent=2, default=str)}")
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
        news_context, trade_history_context, regime_context,
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
