import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_PATTERNS = (
    "head_and_shoulders, inverse_head_and_shoulders, double_top, double_bottom, "
    "triple_top, triple_bottom, ascending_triangle, descending_triangle, "
    "symmetrical_triangle, rising_wedge, falling_wedge, bull_flag, bear_flag, "
    "pennant, cup_and_handle, none"
)

_SYSTEM_PROMPT = f"""You are an expert chart pattern recognition analyst.
Examine the candlestick chart image and identify the most prominent price action pattern.

Valid pattern names: {_PATTERNS}

Return a JSON object with this exact structure:

{{
    "pattern": <str>,
    "completion_state": "forming|complete|breakout_confirmed",
    "confidence": "low|medium|high",
    "bias": "bullish|bearish|neutral"
}}

Rules:
- Choose exactly one pattern from the valid list; use "none" if no clear pattern is visible.
- completion_state: "forming" = pattern in progress, "complete" = pattern fully formed,
  "breakout_confirmed" = price has broken out of the pattern.
- bias reflects the directional implication of the pattern.
- confidence reflects how clearly the pattern is visible.

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


async def run_pattern_agent(
    chart_image_b64: str,
    market_context: dict,
    llm,
) -> tuple[dict, any]:
    """Identify chart patterns from a base64-encoded chart image.

    Args:
        chart_image_b64: Base64-encoded PNG chart image.
        market_context: Supplementary market context (symbol, timeframe, price, etc.).
        llm: Vision-capable LangChain BaseChatModel instance.

    Returns:
        Dict with pattern name, completion state, confidence, and directional bias.
    """
    _fallback = {
        "pattern": "none",
        "confidence": "low",
        "bias": "neutral",
        "completion_state": "forming",
    }

    human_content = [
        {
            "type": "text",
            "text": (
                f"Market context: {json.dumps(market_context)}\n\n"
                "Analyze this candlestick chart and identify the dominant price action pattern. "
                "Return the JSON response as instructed."
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{chart_image_b64}"},
        },
    ]

    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_content)]

    try:
        response = await llm.ainvoke(messages)
        raw = _extract_text(response.content)
        cleaned = _strip_fences(raw)
        result: dict = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError, AttributeError):
        logger.warning("pattern_agent: JSON parse failed, returning neutral fallback")
        return _fallback, None

    logger.info(
        "pattern_agent complete: pattern=%s confidence=%s",
        result.get("pattern"),
        result.get("confidence"),
    )
    return result, response
