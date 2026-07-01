import asyncio
import json
import logging
import re
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from ai.agents.decision_agent import run_decision_agent
from ai.agents.indicator_agent import run_indicator_agent
from ai.agents.pattern_agent import run_pattern_agent
from ai.agents.trend_agent import run_trend_agent
from core.config import Settings

logger = logging.getLogger(__name__)


class AgentPipelineState(TypedDict):
    # Inputs
    symbol: str
    timeframe: str
    current_price: float
    ohlcv: list[dict]
    indicators: dict
    chart_image_b64: str | None
    trendline_chart_b64: str | None
    # Optional context passed from caller
    news_context: str | None
    open_positions: list[dict] | None
    trade_history: list[dict] | None
    trade_history_context: str | None
    context_ohlcv: dict[str, list[dict]] | None
    # Context (filled by market_analysis node)
    market_context: dict | None
    # Agent outputs
    indicator_report: dict | None
    pattern_report: dict | None
    trend_report: dict | None
    # Final
    final_signal: dict | None
    error: str | None
    # Token usage per step — each dict has: input_tokens, output_tokens, total_tokens,
    # model, provider, duration_ms (all fields may be None if not available)
    market_analysis_tokens: dict | None
    indicator_tokens: dict | None
    pattern_tokens: dict | None
    trend_tokens: dict | None
    decision_tokens: dict | None
    # Prompts sent to each agent — {"system": str, "human": str} dicts for UI display
    market_analysis_prompt: dict | None
    indicator_prompt: dict | None
    pattern_prompt: dict | None
    trend_prompt: dict | None
    decision_prompt: dict | None


def _extract_text(content: Any) -> str:
    """Extract plain text from an LLM response content field."""
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences before JSON parsing."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _provider_from_llm(llm: Any) -> str:
    name = type(llm).__name__.lower()
    if "openai" in name or "chatgpt" in name:
        return "openai"
    if "anthropic" in name or "claude" in name:
        return "anthropic"
    if "google" in name or "gemini" in name or "vertex" in name:
        return "google"
    if "ollama" in name:
        return "ollama"
    return "unknown"


def _model_name_from_llm(llm: Any) -> str:
    return getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"


def _build_usage(response: Any | None, llm: Any, duration_ms: int) -> dict:
    """Build a token usage dict from an AIMessage response and its LLM instance."""
    inp: int | None = None
    out: int | None = None
    total: int | None = None
    if response is not None:
        meta = getattr(response, "usage_metadata", None)
        if isinstance(meta, dict):
            inp = meta.get("input_tokens")
            out = meta.get("output_tokens")
            total = meta.get("total_tokens")
        if total is None and inp is not None and out is not None:
            total = inp + out
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": total,
        "model": _model_name_from_llm(llm),
        "provider": _provider_from_llm(llm),
        "duration_ms": duration_ms,
    }


def _make_market_analysis_node(market_analysis_llm: BaseChatModel):
    async def market_analysis_node(state: AgentPipelineState) -> dict:
        symbol = state["symbol"]
        timeframe = state["timeframe"]
        current_price = state["current_price"]
        indicators = state.get("indicators") or {}

        logger.info(
            "market_analysis_node start: symbol=%s timeframe=%s price=%s",
            symbol,
            timeframe,
            current_price,
        )

        system_prompt = (
            "You are a professional forex market analyst. Analyze the market data and return "
            'ONLY valid JSON: {"trend": "bullish|bearish|ranging", "trend_strength": float, '
            '"key_support": float, "key_resistance": float, "volatility": "low|medium|high", '
            '"context_notes": "str"}'
        )

        indicator_summary = json.dumps(indicators, default=str)
        news_context = state.get("news_context")
        open_positions = state.get("open_positions")
        human_text = (
            f"Symbol: {symbol}\n"
            f"Timeframe: {timeframe}\n"
            f"Current Price: {current_price}\n"
            f"Indicators: {indicator_summary}"
        )
        ohlcv = state.get("ohlcv") or []
        if ohlcv:
            recent = ohlcv[-20:]
            ohlcv_rows = ["time,open,high,low,close,volume"]
            for c in recent:
                ohlcv_rows.append(
                    f"{c.get('time', '')},{c.get('open', '')},{c.get('high', '')},"
                    f"{c.get('low', '')},{c.get('close', '')},{c.get('tick_volume', c.get('volume', ''))}"
                )
            human_text += f"\nRecent OHLCV (last {len(recent)} candles):\n" + "\n".join(ohlcv_rows)
        if news_context:
            human_text += f"\nNews Context: {news_context}"
        if open_positions:
            human_text += f"\nOpen Positions: {json.dumps(open_positions, default=str)}"
        trade_history_context = state.get("trade_history_context")
        if trade_history_context:
            human_text += f"\n{trade_history_context}"
        elif (trade_history := state.get("trade_history")):
            human_text += f"\nRecent Trade History: {json.dumps(trade_history[-5:], default=str)}"
        context_ohlcv = state.get("context_ohlcv")
        if context_ohlcv:
            for ctx_tf, ctx_candles in context_ohlcv.items():
                recent_ctx = ctx_candles[-10:]
                rows = ["time,open,high,low,close,volume"]
                for c in recent_ctx:
                    rows.append(
                        f"{c.get('time', '')},{c.get('open', '')},{c.get('high', '')},"
                        f"{c.get('low', '')},{c.get('close', '')},{c.get('tick_volume', c.get('volume', ''))}"
                    )
                human_text += f"\nContext TF {ctx_tf} (last {len(recent_ctx)} candles):\n" + "\n".join(rows)

        prompt_dict = {"system": system_prompt, "human": human_text}
        t0 = time.monotonic()
        try:
            response = await market_analysis_llm.ainvoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=human_text)]
            )
            dur = int((time.monotonic() - t0) * 1000)
            raw = _extract_text(response.content)
            cleaned = _strip_markdown_fences(raw)
            result = json.loads(cleaned)
            logger.info("market_analysis_node finished: trend=%s", result.get("trend"))
            return {
                "market_context": result,
                "market_analysis_tokens": _build_usage(response, market_analysis_llm, dur),
                "market_analysis_prompt": prompt_dict,
            }
        except json.JSONDecodeError as exc:
            dur = int((time.monotonic() - t0) * 1000)
            logger.error("market_analysis_node JSON parse error: %s", exc)
            return {
                "market_context": {},
                "market_analysis_tokens": _build_usage(None, market_analysis_llm, dur),
                "market_analysis_prompt": prompt_dict,
            }
        except Exception as exc:
            dur = int((time.monotonic() - t0) * 1000)
            logger.error("market_analysis_node error: %s", exc)
            return {
                "market_context": {},
                "market_analysis_tokens": _build_usage(None, market_analysis_llm, dur),
                "market_analysis_prompt": prompt_dict,
                "error": str(exc),
            }

    return market_analysis_node


def _make_parallel_agents_node(
    indicator_agent_llm: BaseChatModel,
    chart_vision_llm: BaseChatModel,
    settings: Settings,
):
    async def parallel_agents_node(state: AgentPipelineState) -> dict:
        logger.info("parallel_agents_node start")

        async def _run_indicator() -> tuple[dict | None, dict | None, str]:
            if not settings.enable_indicator_agent:
                return None, None, ""
            try:
                t0 = time.monotonic()
                result, response, prompt = await run_indicator_agent(
                    state["indicators"], state.get("market_context") or {}, indicator_agent_llm
                )
                dur = int((time.monotonic() - t0) * 1000)
                return result, _build_usage(response, indicator_agent_llm, dur), prompt
            except Exception as exc:
                logger.error("indicator_agent error: %s", exc)
                return None, None, ""

        async def _run_pattern() -> tuple[dict | None, dict | None, str]:
            if not settings.enable_pattern_agent:
                return None, None, ""
            if state.get("chart_image_b64") is None:
                return None, None, ""
            try:
                t0 = time.monotonic()
                result, response, prompt = await run_pattern_agent(
                    state["chart_image_b64"], state.get("market_context") or {}, chart_vision_llm
                )
                dur = int((time.monotonic() - t0) * 1000)
                return result, _build_usage(response, chart_vision_llm, dur), prompt
            except Exception as exc:
                logger.error("pattern_agent error: %s", exc)
                return None, None, ""

        async def _run_trend() -> tuple[dict | None, dict | None, str]:
            if not settings.enable_trend_agent:
                return None, None, ""
            if state.get("trendline_chart_b64") is None:
                return None, None, ""
            try:
                t0 = time.monotonic()
                result, response, prompt = await run_trend_agent(
                    state["trendline_chart_b64"], state.get("market_context") or {}, chart_vision_llm
                )
                dur = int((time.monotonic() - t0) * 1000)
                return result, _build_usage(response, chart_vision_llm, dur), prompt
            except Exception as exc:
                logger.error("trend_agent error: %s", exc)
                return None, None, ""

        (
            (indicator_report, indicator_tokens, indicator_prompt),
            (pattern_report, pattern_tokens, pattern_prompt),
            (trend_report, trend_tokens, trend_prompt),
        ) = await asyncio.gather(_run_indicator(), _run_pattern(), _run_trend())

        logger.info(
            "parallel_agents_node finished: indicator=%s pattern=%s trend=%s",
            indicator_report is not None,
            pattern_report is not None,
            trend_report is not None,
        )

        return {
            "indicator_report": indicator_report,
            "pattern_report": pattern_report,
            "trend_report": trend_report,
            "indicator_tokens": indicator_tokens,
            "pattern_tokens": pattern_tokens,
            "trend_tokens": trend_tokens,
            "indicator_prompt": indicator_prompt or None,
            "pattern_prompt": pattern_prompt or None,
            "trend_prompt": trend_prompt or None,
        }

    return parallel_agents_node


def _make_decision_node(execution_decision_llm: BaseChatModel):
    async def decision_node(state: AgentPipelineState) -> dict:
        logger.info("decision_node start")
        t0 = time.monotonic()
        try:
            result, response, prompt = await run_decision_agent(
                state.get("indicator_report"),
                state.get("pattern_report"),
                state.get("trend_report"),
                state.get("market_context"),
                execution_decision_llm,
            )
            dur = int((time.monotonic() - t0) * 1000)
            logger.info(
                "decision_node finished: signal=%s confidence=%s",
                result.get("signal"),
                result.get("confidence"),
            )
            return {
                "final_signal": result,
                "decision_tokens": _build_usage(response, execution_decision_llm, dur),
                "decision_prompt": prompt or None,
            }
        except Exception as exc:
            dur = int((time.monotonic() - t0) * 1000)
            logger.error("decision_node error: %s", exc)
            return {
                "final_signal": {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "justification": "pipeline_error",
                },
                "decision_tokens": _build_usage(None, execution_decision_llm, dur),
                "decision_prompt": None,
            }

    return decision_node


def build_pipeline(
    market_analysis_llm: BaseChatModel,
    indicator_agent_llm: BaseChatModel,
    chart_vision_llm: BaseChatModel,
    execution_decision_llm: BaseChatModel,
    settings: Settings,
) -> Any:  # CompiledGraph
    """Build and compile the multi-agent trading pipeline graph."""
    logger.info("build_pipeline: constructing StateGraph")

    graph = StateGraph(AgentPipelineState)

    graph.add_node(
        "market_analysis",
        _make_market_analysis_node(market_analysis_llm),
    )
    graph.add_node(
        "parallel_agents",
        _make_parallel_agents_node(indicator_agent_llm, chart_vision_llm, settings),
    )
    graph.add_node(
        "decision",
        _make_decision_node(execution_decision_llm),
    )

    graph.set_entry_point("market_analysis")
    graph.add_edge("market_analysis", "parallel_agents")
    graph.add_edge("parallel_agents", "decision")
    graph.add_edge("decision", END)

    compiled = graph.compile()
    logger.info("build_pipeline: graph compiled successfully")
    return compiled
