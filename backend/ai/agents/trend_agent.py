import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a professional trendline and channel analyst.
Blue line = support trendline. Red line = resistance trendline.

Examine the chart image and return a JSON object with this exact structure:

{
    "trendline_structure": "ascending_channel|descending_channel|triangle|horizontal|other",
    "price_position": "above_support|at_resistance|between_levels|below_support",
    "trend_prediction": "upward|downward|sideways",
    "key_levels": {"support": <float>, "resistance": <float>},
    "confidence": "low|medium|high"
}

Rules:
- trendline_structure: describe the overall geometric structure formed by the two trendlines.
- price_position: where current price sits relative to the drawn trendlines.
- trend_prediction: most likely near-term directional move given the structure.
- key_levels: read the approximate price values of support and resistance from the chart.
- confidence: how clearly the trendlines are defined and readable.

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


async def run_trend_agent(
    trendline_chart_b64: str,
    market_context: dict,
    llm,
) -> tuple[dict, any]:
    """Analyze trendline structure from a base64-encoded chart image.

    Args:
        trendline_chart_b64: Base64-encoded PNG chart with blue support and red resistance lines.
        market_context: Supplementary market context (symbol, timeframe, price, etc.).
        llm: Vision-capable LangChain BaseChatModel instance.

    Returns:
        Dict describing trendline structure, price position, prediction, key levels, and confidence.
    """
    _fallback = {
        "trendline_structure": "other",
        "price_position": "between_levels",
        "trend_prediction": "sideways",
        "key_levels": {"support": 0.0, "resistance": 0.0},
        "confidence": "low",
    }

    human_content = [
        {
            "type": "text",
            "text": (
                f"Market context: {json.dumps(market_context)}\n\n"
                "Analyze the trendlines on this chart (blue = support, red = resistance) "
                "and return the JSON response as instructed."
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{trendline_chart_b64}"},
        },
    ]

    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_content)]

    try:
        response = await llm.ainvoke(messages)
        raw = _extract_text(response.content)
        cleaned = _strip_fences(raw)
        result: dict = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError, AttributeError):
        logger.warning("trend_agent: JSON parse failed, returning neutral fallback")
        return _fallback, None

    logger.info(
        "trend_agent complete: structure=%s prediction=%s confidence=%s",
        result.get("trendline_structure"),
        result.get("trend_prediction"),
        result.get("confidence"),
    )
    return result, response
