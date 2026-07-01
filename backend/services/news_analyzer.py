"""ForexFactory news LLM analyzer.

Runs pre-release LLM analysis on stored EconomicEvent rows using the
task-assigned provider/model for the "news_analysis" task.

Schedule: daily at 00:00 UTC (07:00 Bangkok) via scheduler.
Manual trigger: POST /api/v1/news/{id}/analyze  or  POST /api/v1/news/analyze-today
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EconomicEvent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a forex market analyst specialising in economic news impact.

Given an upcoming economic event, analyse its likely short-term price impact on
the listed currency pairs and provide a concise forecast.

Respond with valid JSON only — no markdown fences:
{
  "signal": "BUY" | "SELL" | "HOLD" | "AVOID",
  "summary": "<2-3 sentences explaining the expected market reaction>",
  "affected_symbols_detail": {"EURUSD": "<brief reason>", ...}
}

Signal definitions:
- BUY   = event likely to push the base currency UP (positive surprise expected)
- SELL  = event likely to push the base currency DOWN (negative surprise expected)
- HOLD  = impact unclear, mixed, or too early to call
- AVOID = high-volatility event; avoid new positions until actual data is released
- When forecast equals previous or forecast is absent, prefer HOLD or AVOID for HIGH impact events.
"""


async def _resolve_llm(db: AsyncSession) -> Any:
    """Return a LangChain LLM for the news_analysis task, or the default LLM."""
    from ai.orchestrator import _build_llm
    from services.ai_trading import _get_task_llm

    llm = await _get_task_llm("news_analysis", db)
    return llm or _build_llm()


def _build_human_prompt(event: EconomicEvent) -> str:
    now_utc = datetime.now(UTC)
    minutes_until = int((event.event_utc - now_utc).total_seconds() / 60)
    time_label = (
        f"in {minutes_until} min" if minutes_until > 0
        else f"{abs(minutes_until)} min ago (pre-release analysis)"
    )

    symbols = json.loads(event.affected_symbols) if event.affected_symbols else []

    lines = [
        f"Event: {event.title}",
        f"Currency: {event.currency}",
        f"Impact: {event.impact}",
        f"Scheduled: {event.event_utc.strftime('%Y-%m-%d %H:%M')} UTC ({time_label})",
    ]
    if event.forecast:
        lines.append(f"Forecast: {event.forecast}")
    if event.previous:
        lines.append(f"Previous: {event.previous}")
    if symbols:
        lines.append(f"Affected symbols: {', '.join(symbols)}")

    return "\n".join(lines)


async def analyze_event(event: EconomicEvent, db: AsyncSession) -> None:
    """Run LLM analysis on a single event and update the DB row.

    Never raises — errors are stored in event.analysis_error.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from ai.orchestrator import _call_llm_for_role
    from core.llm_pricing import compute_cost
    from db.models import LLMCall

    try:
        llm = await _resolve_llm(db)
        human_text = _build_human_prompt(event)

        result = await _call_llm_for_role(
            llm,
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_text)],
            "news_analysis",
        )

        # Robustly extract the parsed dict — re-try raw_text if _call_llm_for_role
        # fell back to returning the string (happens when LLM wraps JSON in fences).
        raw: dict = result.content if isinstance(result.content, dict) else {}
        if not raw and result.raw_text:
            try:
                import re as _re
                # Strip any markdown code fences (```json ... ```)
                text = _re.sub(r"^```[a-z]*\n?", "", result.raw_text.strip(), flags=_re.IGNORECASE)
                text = _re.sub(r"\n?```$", "", text.strip())
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    raw = parsed
            except Exception:
                pass

        signal = str(raw.get("signal", "HOLD")).upper()
        if signal not in {"BUY", "SELL", "HOLD", "AVOID"}:
            signal = "HOLD"

        cost = compute_cost(result.model, result.input_tokens or 0, result.output_tokens or 0)

        event.llm_signal = signal
        event.llm_summary = raw.get("summary") or None
        event.llm_provider = result.provider
        event.llm_model = result.model
        event.llm_analyzed_at = datetime.now(UTC)
        event.llm_input_tokens = result.input_tokens
        event.llm_output_tokens = result.output_tokens
        event.llm_total_tokens = result.total_tokens
        event.llm_cost_usd = cost
        event.llm_duration_ms = result.duration_ms
        event.llm_raw_response = result.raw_text
        event.analysis_error = None

        # Log to llm_calls for LLM Usage tracking
        db.add(LLMCall(
            pipeline_step_id=None,
            account_id=None,
            provider=result.provider,
            model=result.model,
            role="news_analysis",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            cost_usd=cost,
            duration_ms=result.duration_ms,
        ))

        logger.info(
            "News event analyzed | id=%d title=%r signal=%s provider=%s in=%s out=%s cost_usd=%s",
            event.id, event.title, signal, result.provider,
            result.input_tokens, result.output_tokens, cost,
        )

    except Exception as exc:
        event.analysis_error = str(exc)
        logger.warning("News analysis failed | id=%d title=%r error=%s", event.id, event.title, exc)

    await db.commit()


async def analyze_today_events(db: AsyncSession) -> int:
    """Analyze all HIGH-impact events in the next 24 h that have no LLM signal yet.

    Returns the number of events analyzed.
    """
    now_utc = datetime.now(UTC)
    window_end = now_utc + timedelta(hours=24)

    result = await db.execute(
        select(EconomicEvent).where(
            EconomicEvent.impact == "High",
            EconomicEvent.event_utc >= now_utc,
            EconomicEvent.event_utc <= window_end,
            EconomicEvent.llm_signal.is_(None),
        )
    )
    events = result.scalars().all()

    logger.info("Analyzing %d upcoming HIGH-impact events", len(events))
    for event in events:
        await analyze_event(event, db)

    return len(events)
