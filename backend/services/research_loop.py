"""Research Loop Service — periodic auto-adjustment every N closed trades.

Triggered from accounts.py sync when closed_trade_count % RESEARCH_EVERY == 0.

What it does:
  1. Queries performance stats from DB
  2. Calls LLM (post_trade_analysis model) to interpret patterns and suggest adjustments
  3. Writes backend/data/research_config.json with:
       - lessons:        list of string lessons injected into RAG context
       - signal_weights: dict of signal_name -> reliability score (0.0-1.0)
       - blocked_symbols: list of symbols auto-flagged for poor performance
       - suggested_params: dict of parameter suggestions (not auto-applied)
       - last_run_at:    ISO timestamp

research_config.json is read by:
  - rag_context.py   (lessons section)
  - (future) orchestrator can read suggested_params to tune thresholds
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RESEARCH_EVERY = 30  # run after every N closed trades
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CONFIG_PATH = os.path.join(_DATA_DIR, "research_config.json")


async def maybe_run(account_id: int, db: AsyncSession, newly_closed: int = 1) -> None:
    """Call after each trade close. Runs the loop when the count crosses a RESEARCH_EVERY boundary.

    Uses crossing logic so batch syncs (e.g. 28→33) don't skip the threshold.
    """
    try:
        count = await _count_closed_trades(db, account_id)
        prev_count = max(count - newly_closed, 0)
        if count // RESEARCH_EVERY > prev_count // RESEARCH_EVERY:
            logger.info("research_loop triggered | account_id=%s closed_trades=%s", account_id, count)
            await run(account_id, db)
    except Exception:
        logger.exception("research_loop.maybe_run failed | account_id=%s", account_id)


async def run(account_id: int, db: AsyncSession) -> None:
    """Run the full research loop and write research_config.json."""
    stats = await _gather_stats(db, account_id)
    config = await _llm_review(stats, db)
    _write_config(config)
    logger.info(
        "research_loop complete | lessons=%d blocked_symbols=%s",
        len(config.get("lessons", [])),
        config.get("blocked_symbols", []),
    )


# ── Stats gathering ───────────────────────────────────────────────────────────

async def _count_closed_trades(db: AsyncSession, account_id: int) -> int:
    from db.models import Trade
    from sqlalchemy import func, select
    row = (
        await db.execute(
            select(func.count(Trade.id)).where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
            )
        )
    ).scalar_one()
    return row or 0


async def _gather_stats(db: AsyncSession, account_id: int) -> dict:
    from db.models import AIJournal, Trade
    from sqlalchemy import func, select

    since = datetime.now(UTC) - timedelta(days=90)

    # Overall
    overall = (
        await db.execute(
            select(
                func.count(Trade.id).label("total"),
                func.count(Trade.id).filter(Trade.profit > 0).label("wins"),
                func.coalesce(func.sum(Trade.profit), 0.0).label("pnl"),
            ).where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.closed_at >= since,
            )
        )
    ).one()

    # By symbol
    sym_rows = (
        await db.execute(
            select(
                Trade.symbol,
                func.count(Trade.id).label("n"),
                func.count(Trade.id).filter(Trade.profit > 0).label("w"),
                func.coalesce(func.sum(Trade.profit), 0.0).label("pnl"),
            )
            .where(Trade.account_id == account_id, Trade.closed_at.is_not(None), Trade.closed_at >= since)
            .group_by(Trade.symbol)
        )
    ).all()

    # Signal reliability from trade_analysis
    recent_trades = (
        await db.execute(
            select(Trade.trade_analysis, Trade.profit)
            .where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.trade_analysis.is_not(None),
            )
            .order_by(Trade.closed_at.desc())
            .limit(100)
        )
    ).all()

    sig_counts: dict[str, dict[str, int]] = {}
    lessons_from_losses: list[str] = []
    for ta_json, profit in recent_trades:
        try:
            ta = json.loads(ta_json)
            for s in ta.get("correct_signals", []):
                sig_counts.setdefault(s, {"correct": 0, "wrong": 0})["correct"] += 1
            for s in ta.get("wrong_signals", []):
                sig_counts.setdefault(s, {"correct": 0, "wrong": 0})["wrong"] += 1
            if (profit or 0) < 0 and ta.get("lesson"):
                lessons_from_losses.append(ta["lesson"])
        except Exception:
            continue

    signal_reliability = {
        s: round(c["correct"] / max(c["correct"] + c["wrong"], 1), 2)
        for s, c in sig_counts.items()
    }

    # Confidence calibration
    cal_rows = (
        await db.execute(
            select(AIJournal.confidence, Trade.profit)
            .join(Trade, AIJournal.trade_id == Trade.id)
            .where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.closed_at >= since,
                AIJournal.confidence.is_not(None),
            )
        )
    ).all()

    high_conf_wins = sum(1 for c, p in cal_rows if (c or 0) >= 0.75 and (p or 0) > 0)
    high_conf_total = sum(1 for c, _ in cal_rows if (c or 0) >= 0.75)
    high_conf_wr = high_conf_wins / high_conf_total if high_conf_total else None

    return {
        "account_id": account_id,
        "period_days": 90,
        "overall": {
            "total": overall.total,
            "wins": overall.wins,
            "win_rate": round(overall.wins / overall.total, 3) if overall.total else 0,
            "pnl": round(overall.pnl, 2),
        },
        "by_symbol": [
            {
                "symbol": r.symbol,
                "n": r.n,
                "win_rate": round(r.w / r.n, 3) if r.n else 0,
                "pnl": round(r.pnl, 2),
            }
            for r in sym_rows
        ],
        "signal_reliability": signal_reliability,
        "high_conf_win_rate": round(high_conf_wr, 3) if high_conf_wr is not None else None,
        "recent_loss_lessons": lessons_from_losses[:10],
    }


# ── LLM review ────────────────────────────────────────────────────────────────

async def _llm_review(stats: dict, db: AsyncSession) -> dict:
    """Ask the LLM to interpret stats and suggest adjustments."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from services.ai_trading import _get_task_llm

    llm = await _get_task_llm("post_trade_analysis", db)

    system = (
        "You are a quantitative trading system analyst reviewing performance data. "
        "Analyze the statistics and provide actionable insights. "
        "Return ONLY valid JSON with no markdown."
    )

    human = (
        f"Review the following trading performance statistics and return JSON:\n\n"
        f"{json.dumps(stats, indent=2)}\n\n"
        f"Return ONLY this JSON structure:\n"
        f"{{\n"
        f'  "lessons": ["<lesson 1>", "<lesson 2>", ...],  // 3-5 short actionable lessons\n'
        f'  "blocked_symbols": ["<symbol>", ...],           // symbols with WR < 40% and n >= 20\n'
        f'  "suggested_params": {{                           // optional parameter suggestions\n'
        f'    "confidence_threshold": <float 0.5-0.9>,\n'
        f'    "notes": "<brief rationale>"\n'
        f'  }}\n'
        f"}}\n"
        f"Base blocked_symbols only on symbols where win_rate < 0.40 and n >= 20.\n"
        f"Keep lessons concise (max 100 chars each)."
    )

    try:
        ai_msg = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
        from ai.orchestrator import log_llm_usage
        log_llm_usage(ai_msg, llm, "research_loop")
        raw = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
    except Exception as exc:
        logger.warning("research_loop LLM review failed (%s) — using rule-based fallback", exc)
        result = _rule_based_review(stats)

    result["last_run_at"] = datetime.now(UTC).isoformat()
    result["stats_snapshot"] = {
        "total_trades": stats["overall"]["total"],
        "win_rate": stats["overall"]["win_rate"],
        "pnl": stats["overall"]["pnl"],
    }
    return result


def _rule_based_review(stats: dict) -> dict:
    """Fallback when LLM call fails — derive lessons from raw stats."""
    lessons: list[str] = []
    blocked: list[str] = []

    wr = stats["overall"].get("win_rate", 0)
    if wr < 0.45:
        lessons.append(f"Overall WR is {wr:.0%} — be more selective, require higher confluence.")
    if wr > 0.60:
        lessons.append(f"WR is {wr:.0%} — system is performing well, maintain current approach.")

    hc_wr = stats.get("high_conf_win_rate")
    if hc_wr is not None and hc_wr < 0.50:
        lessons.append("High-confidence signals are underperforming — reduce over-confidence bias.")

    for sym in stats.get("by_symbol", []):
        if sym["n"] >= 20 and sym["win_rate"] < 0.40:
            blocked.append(sym["symbol"])
            lessons.append(f"{sym['symbol']} WR is {sym['win_rate']:.0%} — auto-blocked.")

    for lesson in stats.get("recent_loss_lessons", [])[:3]:
        lessons.append(lesson)

    return {"lessons": lessons[:5], "blocked_symbols": blocked, "suggested_params": {}}


# ── Config I/O ────────────────────────────────────────────────────────────────

def _write_config(config: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def read_config() -> dict:
    """Read current research config. Returns empty dict if not yet generated."""
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}
