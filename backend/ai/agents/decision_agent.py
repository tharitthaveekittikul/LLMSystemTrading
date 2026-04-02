import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a QuantAgent — a senior quantitative trading analyst who synthesizes
multi-source market intelligence into a single actionable trading decision.

You receive three analytical reports with the following weights:
  - Momentum Indicators Report (40% weight): RSI, MACD, Stochastic, ROC, Williams %R
  - Chart Pattern Report (35% weight): identified price action pattern and its implications
  - Trendline Report (25% weight): channel/trendline structure and key support/resistance levels

Apply these weights when forming your decision. A report listed as "not available" should be
excluded from the weighted average and its weight redistributed proportionally to the others.

Return a JSON object with this exact structure:

{
    "forecast_horizon": <str>,
    "signal": "BUY_LIMIT|SELL_LIMIT|BUY_STOP|SELL_STOP|HOLD",
    "confidence": <float between 0.0 and 1.0>,
    "justification": <str>,
    "risk_reward_ratio": <float>,
    "suggested_entry": <float>,
    "stop_loss": <float>,
    "take_profit": <float>,
    "expiry_multiplier": <float between 0.5 and 3.0>,
    "invalidation_condition": <str>
}

Rules:
- signal: BUY_LIMIT = place a buy pending order below the current price (expect price to dip then rise).
          SELL_LIMIT = place a sell pending order above the current price (expect price to spike then fall).
          BUY_STOP = place a buy pending order above the current price (breakout buy).
          SELL_STOP = place a sell pending order below the current price (breakout sell).
          HOLD = no position / wait for better setup.
          Never use immediate market orders — always use pending orders.
- confidence: weighted average conviction (0.0 = no confidence, 1.0 = maximum confidence).
- justification: concise explanation referencing the reports, max 3 sentences.
- risk_reward_ratio: expected reward divided by expected risk (e.g. 2.0 means 2:1 R:R).
- suggested_entry: approximate price level to enter the trade (use 0.0 if HOLD).
- stop_loss: specific price level for stop loss. Must be on the correct side of entry.
             Use 0.0 only if signal is HOLD.
- take_profit: specific price level for take profit. Must respect risk_reward_ratio.
               Use 0.0 only if signal is HOLD.
- expiry_multiplier: multiplier applied to the default 4-candle pending order expiry.
  Use 0.5–0.9 for tight/fast setups (sharp PRZ, high volatility, breakout confirmation needed quickly).
  Use 1.0 for normal setups (default — no strong reason to deviate).
  Use 1.5–3.0 for slow-developing setups (trend continuation, wide range, low volatility).
  Always use 1.0 when signal is HOLD (value is ignored but must be present).
- invalidation_condition: describe the price event that would invalidate this signal.
- forecast_horizon: estimated timeframe for the trade (e.g. "4-8 hours", "1-2 days").

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


def _format_report(name: str, report: dict | None) -> str:
    if report is None:
        return f"{name}: not available"
    return f"{name}:\n{json.dumps(report, indent=2)}"


async def run_decision_agent(
    indicator_report: dict | None,
    pattern_report: dict | None,
    trend_report: dict | None,
    market_context: dict,
    llm,
) -> tuple[dict, any, str]:
    """Synthesize sub-agent reports into a final trading decision.

    Args:
        indicator_report: Output from run_indicator_agent, or None if unavailable.
        pattern_report: Output from run_pattern_agent, or None if unavailable.
        trend_report: Output from run_trend_agent, or None if unavailable.
        market_context: Supplementary market context (symbol, timeframe, price, etc.).
        llm: LangChain BaseChatModel instance.

    Returns:
        Tuple of (result_dict, ai_message). result_dict has signal, confidence, justification,
        entry, R:R, and invalidation condition. ai_message is None on parse failure.
    """
    _fallback = {
        "signal": "HOLD",
        "confidence": 0.0,
        "justification": "parse_failed",
        "forecast_horizon": "unknown",
        "risk_reward_ratio": 1.0,
        "suggested_entry": 0.0,
        "stop_loss": 0.0,
        "take_profit": 0.0,
        "expiry_multiplier": 1.0,
        "invalidation_condition": "unknown",
    }

    human_text = (
        f"Market context: {json.dumps(market_context)}\n\n"
        f"{_format_report('Momentum Indicators Report (40% weight)', indicator_report)}\n\n"
        f"{_format_report('Chart Pattern Report (35% weight)', pattern_report)}\n\n"
        f"{_format_report('Trendline Report (25% weight)', trend_report)}\n\n"
        "Based on these reports and their respective weights, provide your trading decision."
    )

    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_text)]

    try:
        response = await llm.ainvoke(messages)
        raw = _extract_text(response.content)
        cleaned = _strip_fences(raw)
        result: dict = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError, AttributeError):
        logger.warning("decision_agent: JSON parse failed, returning HOLD fallback")
        return _fallback, None, None

    logger.info(
        "decision_agent complete: signal=%s confidence=%.2f",
        result.get("signal"),
        float(result.get("confidence", 0.0)),
    )
    return result, response, {"system": _SYSTEM_PROMPT, "human": human_text}
