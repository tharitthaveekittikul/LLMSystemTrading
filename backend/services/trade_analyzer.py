"""Post-Trade AI Analysis Service.

When a trade closes, this service calls a lightweight LLM to analyze the outcome and store
structured lessons in trades.trade_analysis (JSON).  The analysis feeds into:
  - rag_context.py  (Signal Reliability + Lessons sections)
  - research_loop.py (periodic parameter adjustment)

The LLM used is configurable via Settings → Task Assignments → "Post-Trade Analysis".
Falls back to the default LLM if no assignment is configured.

Output JSON schema:
{
  "correct_signals": ["rsi_oversold", "ema_cross"],   // indicator names that supported the right direction
  "wrong_signals":   ["bollinger_squeeze"],            // indicator names that were misleading
  "key_factor":      "Strong NY momentum aligned with H4 trend",
  "lesson":          "Bollinger squeeze on M15 was noise during high-volatility open",
  "confidence_justified": false                        // was the LLM's stated confidence warranted?
}
"""
from __future__ import annotations

import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def analyze_closed_trade(trade_id: int, db: AsyncSession) -> None:
    """Run post-trade LLM analysis for a single closed trade and persist results.

    Safe to call fire-and-forget — catches all exceptions internally.
    """
    try:
        await _analyze(trade_id, db)
    except Exception:
        logger.exception("post-trade analysis failed | trade_id=%s", trade_id)


async def _analyze(trade_id: int, db: AsyncSession) -> None:
    from db.models import AIJournal, Trade
    from langchain_core.messages import HumanMessage, SystemMessage

    # ── Load trade + journal ──────────────────────────────────────────────────
    trade = await db.get(Trade, trade_id)
    if trade is None:
        logger.warning("post-trade analysis: trade %s not found", trade_id)
        return

    if trade.closed_at is None or trade.profit is None:
        logger.debug("post-trade analysis: trade %s not yet closed, skipping", trade_id)
        return

    if trade.trade_analysis:
        logger.debug("post-trade analysis: trade %s already analyzed, skipping", trade_id)
        return

    # Fetch linked journal entry for entry signals / confidence
    from sqlalchemy import select
    journal: AIJournal | None = (
        await db.execute(select(AIJournal).where(AIJournal.trade_id == trade_id))
    ).scalar_one_or_none()

    # ── Build LLM prompt ──────────────────────────────────────────────────────
    outcome = "WIN" if trade.profit > 0 else "LOSS"
    duration_hrs: float | None = None
    if trade.opened_at and trade.closed_at:
        duration_hrs = (trade.closed_at - trade.opened_at).total_seconds() / 3600

    entry_block = (
        f"Symbol: {trade.symbol}\n"
        f"Direction: {trade.direction}\n"
        f"Entry: {trade.entry_price} | Close: {trade.close_price}\n"
        f"SL: {trade.stop_loss} | TP: {trade.take_profit}\n"
        f"Volume: {trade.volume}\n"
        f"Duration: {duration_hrs:.1f}h\n" if duration_hrs else ""
    )

    journal_block = ""
    if journal:
        journal_block = (
            f"\nLLM Signal at Entry:\n"
            f"  Signal: {journal.signal}\n"
            f"  Confidence: {journal.confidence:.0%}\n"
            f"  Rationale: {journal.rationale[:300]}\n"
        )
        if journal.indicators_snapshot:
            try:
                ind = json.loads(journal.indicators_snapshot)
                journal_block += f"  Indicators: {json.dumps(ind, indent=2)[:400]}\n"
            except Exception:
                pass

    human = (
        f"A trade has closed. Analyze the outcome.\n\n"
        f"=== TRADE DETAILS ===\n"
        f"{entry_block}"
        f"\nOutcome: {outcome}\n"
        f"P&L: {trade.profit:+.2f}\n"
        f"{journal_block}\n"
        f"=== INSTRUCTIONS ===\n"
        f"Return ONLY valid JSON:\n"
        f"{{\n"
        f'  "correct_signals": ["<indicator_name>", ...],\n'
        f'  "wrong_signals": ["<indicator_name>", ...],\n'
        f'  "key_factor": "<one sentence — what drove the outcome>",\n'
        f'  "lesson": "<one sentence — what to remember for future trades>",\n'
        f'  "confidence_justified": <true|false>\n'
        f"}}\n"
        f"Use indicator names from the snapshot (e.g. rsi, ema_cross, macd, bollinger, atr).\n"
        f"If no indicator data is available, use empty arrays."
    )

    system = (
        "You are a professional forex trading coach performing post-trade analysis. "
        "Identify which signals were correct or misleading and extract a concise lesson. "
        "Return ONLY the JSON object with no markdown, no explanation."
    )

    # ── Get configured LLM for post_trade_analysis ───────────────────────────
    from services.ai_trading import _get_task_llm  # local import avoids circular at module level
    llm = await _get_task_llm("post_trade_analysis", db)

    # ── Call LLM ─────────────────────────────────────────────────────────────
    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    ai_msg = await llm.ainvoke(messages)
    from ai.orchestrator import log_llm_usage
    log_llm_usage(ai_msg, llm, "post_trade_analysis")
    raw = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)

    # Strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Validate JSON
    result = json.loads(raw)
    required = {"correct_signals", "wrong_signals", "key_factor", "lesson", "confidence_justified"}
    if not required.issubset(result.keys()):
        raise ValueError(f"LLM response missing required keys: {result.keys()}")

    # ── Persist ───────────────────────────────────────────────────────────────
    trade.trade_analysis = json.dumps(result)
    await db.commit()

    logger.info(
        "post-trade analysis saved | trade_id=%s outcome=%s lesson=%s",
        trade_id, outcome, result.get("lesson", "")[:80],
    )
