"""LangChain Orchestrator — all LLM interactions go through here.

Never call OpenAI / Gemini / Anthropic APIs directly from routes or services.
The signal pipeline: market data → prompt → LLM → TradingSignal (validated).
"""
import json
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
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
class LLMAnalysisResult:
    signal: TradingSignal
    prompt_text: str        # rendered human message sent to the LLM
    raw_response: dict      # raw dict from LLM before Pydantic parsing


# ── LLM factory ───────────────────────────────────────────────────────────────

def _build_llm(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseChatModel:
    """Build a LangChain chat model.

    If provider/api_key/model are given, use them directly (DB-sourced task assignment).
    Otherwise fall back to env-var settings.
    """
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


# ── Prompt template ───────────────────────────────────────────────────────────

_SYSTEM = """You are a professional forex and commodity trading analyst.
Analyze the provided market data and return ONLY a JSON trading signal.

Rules:
- Signal BUY or SELL only when multiple indicators confirm the same direction.
- Signal HOLD when uncertain or when risk/reward is unfavorable.
- Stop loss and take profit must be logical relative to current price and ATR.
- Confidence reflects your conviction based on indicator confluence (0.0 = none, 1.0 = certain).
- CRITICAL: Check your currently open positions before signaling. Avoid doubling into the same
  direction unless confluence is extremely strong (confidence > 0.90). Never open opposing
  positions simultaneously.

Return strictly valid JSON matching this schema:
{{
  "action": "BUY | SELL | HOLD",
  "entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "confidence": <float 0.0-1.0>,
  "rationale": "<brief 1-2 sentence explanation>",
  "timeframe": "<e.g. M15>"
}}"""

_HUMAN = """Symbol: {symbol}
Timeframe: {timeframe}
Current Price: {current_price}

Indicators:
{indicators}
{regime_section}
Last 20 OHLCV candles (oldest → newest):
{ohlcv}
{positions_section}
{signals_section}
{chart_section}
{news_section}
{history_section}
Provide the trading signal JSON."""

_PROMPT = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
_DEFAULT_CHAIN = _PROMPT | _build_llm() | JsonOutputParser()


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
) -> LLMAnalysisResult:
    """Run the full LLM analysis pipeline and return a validated TradingSignal.

    Optional context parameters for LLM memory and awareness:
    - open_positions: current MT5 positions so the LLM knows what trades are open
    - recent_signals: last N AIJournal entries so the LLM remembers recent decisions
    - news_context: formatted upcoming economic events string

    If confidence is below the configured threshold the action is forced to HOLD.
    """
    active_llm = llm_override or _build_llm()

    _mod = type(active_llm).__module__
    if "openai" in _mod:
        effective_provider = "openai"
    elif "google" in _mod or "gemini" in _mod:
        effective_provider = "gemini"
    elif "anthropic" in _mod:
        effective_provider = "anthropic"
    else:
        effective_provider = settings.llm_provider

    logger.info(
        "Analyzing market | provider=%s symbol=%s timeframe=%s price=%s",
        effective_provider, symbol, timeframe, current_price,
    )
    if system_prompt_override:
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt_override), ("human", _HUMAN)])
        chain = prompt | active_llm | JsonOutputParser()
    elif llm_override:
        chain = _PROMPT | active_llm | JsonOutputParser()
    else:
        chain = _DEFAULT_CHAIN

    chart_section = (
        f"\nChart Pattern Analysis:\n{chart_analysis}" if chart_analysis else ""
    )

    if open_positions:
        pos_lines = [
            f"  - {p.get('symbol', symbol)} {p.get('direction', '?')} "
            f"vol={p.get('volume', '?')} profit={p.get('profit', '?')}"
            for p in open_positions
        ]
        positions_section = "\nCurrently Open Positions:\n" + "\n".join(pos_lines)
    else:
        positions_section = "\nCurrently Open Positions: None"

    if recent_signals:
        sig_lines = [
            f"  - {s.get('symbol', symbol)} {s.get('signal', '?')} "
            f"conf={s.get('confidence', '?')} | {s.get('rationale', '')[:80]}"
            for s in recent_signals
        ]
        signals_section = "\nRecent Signal History (newest first):\n" + "\n".join(sig_lines)
    else:
        signals_section = ""

    news_section = f"\n{news_context}" if news_context else ""
    history_section = f"\n{trade_history_context}" if trade_history_context else ""

    prompt_vars = {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": current_price,
        "indicators": json.dumps(indicators, indent=2),
        "ohlcv": json.dumps(ohlcv[-20:], indent=2, default=str),
        "chart_section": chart_section,
        "positions_section": positions_section,
        "signals_section": signals_section,
        "news_section": news_section,
        "history_section": history_section,
        "regime_section": (
            f"Market Regime (HMM):\n{regime_context}" if regime_context else ""
        ),
    }

    # Render prompt text for audit capture (uses Python str.format on the template)
    try:
        prompt_text = _HUMAN.format(**prompt_vars)
    except Exception:
        prompt_text = ""

    raw: dict = await chain.ainvoke(prompt_vars)

    signal = TradingSignal(**raw)

    # Confidence gate — downgrade low-confidence signals to HOLD
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
    return LLMAnalysisResult(signal=signal, prompt_text=prompt_text, raw_response=raw)
