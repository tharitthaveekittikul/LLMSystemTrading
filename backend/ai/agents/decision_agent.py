import json
import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a QuantAgent — a senior quantitative trading analyst who synthesizes
multi-source market intelligence into a single actionable trading decision.

You receive three analytical reports with the following weights:
  - Momentum Indicators Report (40% weight): RSI, MACD, Stochastic, ROC, Williams %R
  - Chart Pattern Report (35% weight): identified price action pattern and its implications
  - Trendline Report (25% weight): channel/trendline structure and key support/resistance levels

Apply these weights when forming your decision. A report listed as "not available" should be
excluded from the weighted average and its weight redistributed proportionally to the others."""


class DecisionResult(BaseModel):
    """Final synthesized trading decision, returned via the LLM's structured output."""

    forecast_horizon: str = Field(
        description='Estimated timeframe for the trade, e.g. "4-8 hours", "1-2 days".'
    )
    signal: Literal["BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "HOLD"] = Field(
        description=(
            "BUY_LIMIT = buy pending order below current price (expect a dip then rise). "
            "SELL_LIMIT = sell pending order above current price (expect a spike then fall). "
            "BUY_STOP = buy pending order above current price (breakout buy). "
            "SELL_STOP = sell pending order below current price (breakout sell). "
            "HOLD = no position / wait for a better setup. "
            "Never use immediate market orders — always use pending orders."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Weighted average conviction (0.0 = no confidence, 1.0 = maximum confidence).",
    )
    justification: str = Field(
        description="Concise explanation referencing the reports, max 3 sentences."
    )
    risk_reward_ratio: float = Field(
        description="Expected reward divided by expected risk (e.g. 2.0 means 2:1 R:R)."
    )
    suggested_entry: float = Field(
        description="Approximate price level to enter the trade (use 0.0 if signal is HOLD)."
    )
    stop_loss: float = Field(
        description=(
            "Specific price level for stop loss, on the correct side of entry. "
            "Use 0.0 only if signal is HOLD."
        )
    )
    take_profit: float = Field(
        description=(
            "Specific price level for take profit, respecting risk_reward_ratio. "
            "Use 0.0 only if signal is HOLD."
        )
    )
    expiry_multiplier: float = Field(
        ge=0.5,
        le=3.0,
        description=(
            "Multiplier applied to the default 4-candle pending order expiry. "
            "Use 0.5-0.9 for tight/fast setups, 1.0 for normal setups (default), "
            "1.5-3.0 for slow-developing setups. Always 1.0 when signal is HOLD."
        ),
    )
    invalidation_condition: str = Field(
        description="Describe the price event that would invalidate this signal."
    )


def _extract_text(content: str | list) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block["text"])
    return "\n".join(parts)


class DecisionParseError(Exception):
    """Raised when the execution-decision LLM's response can't be parsed into a DecisionResult."""


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
    vote_summary: dict | None = None,
) -> tuple[dict, any, str]:
    """Synthesize sub-agent reports into a final trading decision.

    Args:
        indicator_report: Output from run_indicator_agent, or None if unavailable.
        pattern_report: Output from run_pattern_agent, or None if unavailable.
        trend_report: Output from run_trend_agent, or None if unavailable.
        market_context: Supplementary market context (symbol, timeframe, price, etc.).
        llm: LangChain BaseChatModel instance.
        vote_summary: Normalized BUY/SELL/HOLD vote per sub-agent plus the quorum
            verdict (see ai.agent_pipeline._quorum_verdict) — only present when this
            is called with a majority reached, so the decision LLM sees whether it's
            confirming a 2/3 (or 3/3) agreement vs. reconciling a real split.

    Returns:
        Tuple of (result_dict, ai_message, prompt). result_dict has signal, confidence,
        justification, entry, R:R, and invalidation condition.

    Raises:
        DecisionParseError: if the LLM response can't be parsed into a DecisionResult.
            Callers should treat this the same as any other transient LLM failure
            (i.e. retry). Invocation-level errors (network, auth, rate limits) from
            the LLM call itself propagate unwrapped.
    """
    vote_text = ""
    if vote_summary:
        vote_text = (
            f"\n\nSub-agent vote breakdown: {json.dumps(vote_summary, default=str)}\n"
            "A majority of sub-agents already agreed on this direction (or on HOLD) — "
            "use it as corroborating evidence, but still apply your own judgment on "
            "entry/stop/target levels and may still choose HOLD if the reports don't "
            "support a good risk/reward setup."
        )

    human_text = (
        f"Market context: {json.dumps(market_context)}\n\n"
        f"{_format_report('Momentum Indicators Report (40% weight)', indicator_report)}\n\n"
        f"{_format_report('Chart Pattern Report (35% weight)', pattern_report)}\n\n"
        f"{_format_report('Trendline Report (25% weight)', trend_report)}\n\n"
        "Based on these reports and their respective weights, provide your trading decision."
        f"{vote_text}"
    )

    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_text)]

    # Structured output (tool-calling / native JSON schema, depending on provider)
    # guarantees a schema-conforming response instead of asking the model to
    # freehand JSON in prose, which is prone to small syntax slips (trailing
    # commas, etc.) that a naive json.loads() can't recover from.
    structured_llm = llm.with_structured_output(DecisionResult, include_raw=True)
    outcome = await structured_llm.ainvoke(messages)

    response = outcome["raw"]
    parsed = outcome["parsed"]
    if parsed is None:
        raw_text = _extract_text(response.content) if response is not None else ""
        logger.warning(
            "decision_agent: structured output parse failed: %s. raw=%r",
            outcome["parsing_error"], raw_text,
        )
        excerpt = raw_text[:300].replace("\n", " ") if raw_text else "<empty response>"
        raise DecisionParseError(
            f"{outcome['parsing_error']} — raw response: {excerpt!r}"
        ) from outcome["parsing_error"]

    result = parsed.model_dump()

    logger.info(
        "decision_agent complete: signal=%s confidence=%.2f",
        result.get("signal"),
        float(result.get("confidence", 0.0)),
    )
    return result, response, {"system": _SYSTEM_PROMPT, "human": human_text}
