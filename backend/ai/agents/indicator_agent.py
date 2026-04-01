import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a professional technical analyst specializing in momentum indicators.
Analyze the provided indicator values and return a JSON object with the following structure:

{
    "rsi": {"value": <float>, "signal": "overbought|oversold|neutral", "trend": <str>},
    "macd": {"crossover": "bullish|bearish|none", "histogram_trend": <str>, "signal": <str>},
    "stoch": {"k": <float>, "d": <float>, "signal": <str>},
    "roc": {"value": <float>, "signal": <str>},
    "willr": {"value": <float>, "signal": <str>},
    "overall": "bullish|bearish|neutral",
    "confidence": "low|medium|high"
}

Rules:
- RSI > 70 = overbought, RSI < 30 = oversold, otherwise neutral
- MACD crossover: bullish if macd_line crossed above signal, bearish if below, none otherwise
- Stochastic %K > 80 = overbought, < 20 = oversold
- ROC positive = bullish momentum, negative = bearish
- Williams %R > -20 = overbought, < -80 = oversold
- overall and confidence must reflect the consensus of all indicators

Return ONLY valid JSON. No markdown fences, no extra text."""


def _extract_text(content: str | list) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block["text"])
    return "\n".join(parts)


def _strip_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


async def run_indicator_agent(
    indicators: dict,
    market_context: dict,
    llm,
) -> tuple[dict, any, str]:
    """Interpret momentum indicators and return a structured analysis dict.

    Args:
        indicators: Dict with keys rsi, macd_line, macd_signal, macd_histogram,
                    stoch_k, stoch_d, roc, willr.
        market_context: Supplementary market context (symbol, timeframe, price, etc.).
        llm: LangChain BaseChatModel instance.

    Returns:
        Dict with per-indicator signals, overall bias, and confidence level.
    """
    human_text = (
        f"Market context: {json.dumps(market_context)}\n\n"
        f"Indicator values:\n"
        f"  RSI: {indicators.get('rsi')}\n"
        f"  MACD Line: {indicators.get('macd_line')}\n"
        f"  MACD Signal: {indicators.get('macd_signal')}\n"
        f"  MACD Histogram: {indicators.get('macd_histogram')}\n"
        f"  Stochastic %K: {indicators.get('stoch_k')}\n"
        f"  Stochastic %D: {indicators.get('stoch_d')}\n"
        f"  ROC: {indicators.get('roc')}\n"
        f"  Williams %R: {indicators.get('willr')}\n\n"
        "Analyze these indicators and return the JSON response."
    )

    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_text)]

    try:
        response = await llm.ainvoke(messages)
        raw = _extract_text(response.content)
        cleaned = _strip_fences(raw)
        result: dict = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError, AttributeError):
        logger.warning("indicator_agent: JSON parse failed, returning neutral fallback")
        return {"overall": "neutral", "confidence": "low", "error": "parse_failed"}, None, ""

    logger.info(
        "indicator_agent complete: overall=%s confidence=%s",
        result.get("overall"),
        result.get("confidence"),
    )
    return result, response, human_text
