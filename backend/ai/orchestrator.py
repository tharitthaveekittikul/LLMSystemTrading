"""LangChain Orchestrator — all LLM interactions go through here.

Never call OpenAI / Gemini / Anthropic APIs directly from routes or services.
The signal pipeline: market data → prompt → LLM → TradingSignal (validated).
"""
import json
import logging
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


# ── LLM factory ───────────────────────────────────────────────────────────────

def _build_llm() -> BaseChatModel:
    provider = settings.llm_provider
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-1.5-pro",
            google_api_key=settings.gemini_api_key,
            temperature=0,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=settings.anthropic_api_key,
            temperature=0,
        )

    raise ValueError(f"Unknown llm_provider: {provider!r}")


# ── Prompt template ───────────────────────────────────────────────────────────

_SYSTEM = """You are a professional forex and commodity trading analyst.
Analyze the provided market data and return ONLY a JSON trading signal.

Rules:
- Signal BUY or SELL only when multiple indicators confirm the same direction.
- Signal HOLD when uncertain or when risk/reward is unfavorable.
- Stop loss and take profit must be logical relative to current price and ATR.
- Confidence reflects your conviction based on indicator confluence (0.0 = none, 1.0 = certain).

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

Last 20 OHLCV candles (oldest → newest):
{ohlcv}
{chart_section}
Provide the trading signal JSON."""

_PROMPT = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])


# ── Public API ────────────────────────────────────────────────────────────────

async def analyze_market(
    symbol: str,
    timeframe: str,
    current_price: float,
    indicators: dict[str, Any],
    ohlcv: list[dict[str, Any]],
    chart_analysis: str | None = None,
) -> TradingSignal:
    """Run the full LLM analysis pipeline and return a validated TradingSignal.

    If confidence is below the configured threshold the action is forced to HOLD.
    """
    logger.info(
        "Analyzing market | provider=%s symbol=%s timeframe=%s price=%s",
        settings.llm_provider, symbol, timeframe, current_price,
    )

    llm = _build_llm()
    chain = _PROMPT | llm | JsonOutputParser()

    chart_section = (
        f"\nChart Pattern Analysis:\n{chart_analysis}" if chart_analysis else ""
    )

    raw: dict = await chain.ainvoke(
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "indicators": json.dumps(indicators, indent=2),
            "ohlcv": json.dumps(ohlcv[-20:], indent=2, default=str),
            "chart_section": chart_section,
        }
    )

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
    return signal
