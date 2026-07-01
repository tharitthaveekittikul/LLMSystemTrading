"""Research Loop Service — periodic auto-adjustment every N closed trades.

Triggered from accounts.py sync when closed_trade_count % RESEARCH_EVERY == 0.

What it does:
  1. Runs a LangChain tool-calling agent that queries DB stats via @tool functions
  2. Agent decides what to investigate (overall perf, per-symbol, signal reliability, loss lessons)
  3. Agent calls save_research_config tool with its findings, which writes backend/data/research_config.json:
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
import math
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RESEARCH_EVERY = 30  # run after every N closed trades
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CONFIG_PATH = os.path.join(_DATA_DIR, "research_config.json")

# ── Confidence-gate modulation tuning ──────────────────────────────────────────
# A symbol needs at least this many closed trades in the trailing window before
# its trust score is allowed to move far from the neutral 0.5 — a handful of
# trades shouldn't swing the confidence gate.
TRUST_MIN_SAMPLE = 20
TRUST_SENSITIVITY = 0.3
TRUST_MIN_THRESHOLD = 0.4
TRUST_MAX_THRESHOLD = 0.9


async def maybe_run(account_id: int, db: AsyncSession) -> None:
    """Call after each trade close. Runs when trades since last successful run reaches RESEARCH_EVERY."""
    try:
        count = await _count_closed_trades(db, account_id)
        last_run_count = read_config().get("trade_count_at_run", 0)
        if count - last_run_count >= RESEARCH_EVERY:
            logger.info("research_loop triggered | account_id=%s closed_trades=%s since_last=%s", account_id, count, count - last_run_count)
            await run(account_id, db)
    except Exception:
        logger.exception("research_loop.maybe_run failed | account_id=%s", account_id)


async def run(account_id: int, db: AsyncSession) -> None:
    """Run the full research loop and write research_config.json."""
    config = await _run_research_agent(account_id, db)
    config["trade_count_at_run"] = await _count_closed_trades(db, account_id)
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    from db.models import Trade
    max_id = (await db.execute(sa_select(func.max(Trade.id)).where(Trade.account_id == account_id))).scalar() or 0
    config["last_trade_id_at_run"] = max_id

    # Computed deterministically in Python from raw DB stats, independent of
    # whether the LLM agent (above) succeeded or fell back to the rule-based
    # path — this is the value the confidence gate actually reads, not
    # `blocked_symbols` (kept for observability/backward-compat only).
    config["symbol_trust_scores"] = await compute_symbol_trust_scores(db, account_id)

    _write_config(config)
    logger.info(
        "research_loop complete | lessons=%d blocked_symbols=%s trust_scores=%s",
        len(config.get("lessons", [])),
        config.get("blocked_symbols", []),
        config.get("symbol_trust_scores", {}),
    )


# ── Agent ─────────────────────────────────────────────────────────────────────

async def _run_research_agent(account_id: int, db: AsyncSession) -> dict:
    """Run research as a LangChain tool-calling agent.

    The agent decides which data to query, then calls save_research_config
    to record its findings. Falls back to rule-based review on any failure.
    """
    from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.tools import tool

    from services.ai_trading import _get_task_llm

    # Mutable container for the agent's final output (populated by save_research_config tool)
    _saved: list[dict] = []

    # ── Tools (async closures capturing db and account_id) ────────────────────

    @tool
    async def get_overall_stats(days: int = 90) -> str:
        """Get overall trading performance: total trades, win rate, total PnL for the past N days."""
        from sqlalchemy import func, select

        from db.models import Trade

        since = datetime.now(UTC) - timedelta(days=days)
        row = (
            await db.execute(
                select(
                    func.count(Trade.id).label("total"),
                    func.count(Trade.id).filter(Trade.profit > 0).label("wins"),
                    func.coalesce(func.sum(Trade.profit), 0.0).label("pnl"),
                ).where(
                    Trade.account_id == account_id,
                    Trade.closed_at.is_not(None),
                    Trade.closed_at >= since,
                    Trade.profit != 0,
                )
            )
        ).one()
        total = row.total or 0
        return json.dumps({
            "total_trades": total,
            "wins": row.wins or 0,
            "win_rate": round((row.wins or 0) / total, 3) if total else 0,
            "pnl": round(float(row.pnl), 2),
            "period_days": days,
        })

    @tool
    async def get_symbol_stats(days: int = 90) -> str:
        """Get per-symbol trading breakdown: trade count, win rate, PnL for each symbol."""
        from sqlalchemy import func, select

        from db.models import Trade

        since = datetime.now(UTC) - timedelta(days=days)
        rows = (
            await db.execute(
                select(
                    Trade.symbol,
                    func.count(Trade.id).label("n"),
                    func.count(Trade.id).filter(Trade.profit > 0).label("w"),
                    func.coalesce(func.sum(Trade.profit), 0.0).label("pnl"),
                )
                .where(Trade.account_id == account_id, Trade.closed_at.is_not(None), Trade.closed_at >= since, Trade.profit != 0)
                .group_by(Trade.symbol)
            )
        ).all()
        return json.dumps([
            {
                "symbol": r.symbol,
                "trades": r.n,
                "win_rate": round(r.w / r.n, 3) if r.n else 0,
                "pnl": round(float(r.pnl), 2),
            }
            for r in rows
        ])

    @tool
    async def get_signal_reliability() -> str:
        """Get reliability scores for trading signals derived from the last 100 trade analyses."""
        from sqlalchemy import select

        from db.models import Trade

        rows = (
            await db.execute(
                select(Trade.trade_analysis, Trade.profit)
                .where(
                    Trade.account_id == account_id,
                    Trade.closed_at.is_not(None),
                    Trade.trade_analysis.is_not(None),
                    Trade.profit != 0,
                )
                .order_by(Trade.closed_at.desc())
                .limit(100)
            )
        ).all()
        sig_counts: dict[str, dict[str, int]] = {}
        for ta_json, _ in rows:
            try:
                ta = json.loads(ta_json)
                for s in ta.get("correct_signals", []):
                    sig_counts.setdefault(s, {"correct": 0, "wrong": 0})["correct"] += 1
                for s in ta.get("wrong_signals", []):
                    sig_counts.setdefault(s, {"correct": 0, "wrong": 0})["wrong"] += 1
            except Exception:
                continue
        return json.dumps({
            s: round(c["correct"] / max(c["correct"] + c["wrong"], 1), 2)
            for s, c in sig_counts.items()
        })

    @tool
    async def get_loss_lessons(limit: int = 10) -> str:
        """Get lessons extracted from recent losing trades (from trade_analysis.lesson field)."""
        from sqlalchemy import select

        from db.models import Trade

        rows = (
            await db.execute(
                select(Trade.trade_analysis, Trade.profit)
                .where(
                    Trade.account_id == account_id,
                    Trade.closed_at.is_not(None),
                    Trade.trade_analysis.is_not(None),
                    Trade.profit != 0,
                )
                .order_by(Trade.closed_at.desc())
                .limit(200)
            )
        ).all()
        lessons = []
        for ta_json, profit in rows:
            if len(lessons) >= limit:
                break
            try:
                ta = json.loads(ta_json)
                if (profit or 0) < 0 and ta.get("lesson"):
                    lessons.append(ta["lesson"])
            except Exception:
                continue
        return json.dumps(lessons)

    @tool
    def save_research_config(
        lessons: list[str],
        blocked_symbols: list[str],
        confidence_threshold: float = 0.0,
        notes: str = "",
    ) -> str:
        """Save research findings. Call this when your analysis is complete.

        Args:
            lessons: 3-5 actionable lessons learned, max 100 chars each.
            blocked_symbols: symbols to auto-block due to poor performance.
            confidence_threshold: suggested min confidence (0.5-0.9), or 0 to leave unchanged.
            notes: brief rationale for the suggestions.
        """
        _saved.append({
            "lessons": lessons[:5],
            "blocked_symbols": blocked_symbols,
            "suggested_params": (
                {"confidence_threshold": confidence_threshold, "notes": notes}
                if confidence_threshold and confidence_threshold > 0
                else {}
            ),
        })
        return "Research config saved."

    tools = [get_overall_stats, get_symbol_stats, get_signal_reliability, get_loss_lessons, save_research_config]

    llm = await _get_task_llm("post_trade_analysis", db)

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a quantitative trading system analyst reviewing account performance. "
            "Use the tools to gather data, identify patterns, and produce actionable insights.\n\n"
            "Workflow:\n"
            "1. Call get_overall_stats to understand the big picture\n"
            "2. Call get_symbol_stats to identify weak/strong symbols\n"
            "3. Call get_signal_reliability to assess which signals to trust\n"
            "4. Call get_loss_lessons to learn from recent mistakes\n"
            "5. Call save_research_config with your conclusions\n\n"
            "Rules:\n"
            "- Block symbols ONLY when win_rate < 0.40 AND trades >= 20\n"
            "- Keep each lesson concise (max 100 chars)\n"
            "- Provide 3-5 lessons total",
        ),
        (
            "human",
            "Analyze trading performance for account {account_id} and save your research findings.",
        ),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools, max_iterations=10, verbose=False)

    try:
        await executor.ainvoke({"account_id": account_id})
    except Exception as exc:
        logger.warning("research_loop agent failed (%s) — using rule-based fallback", exc)
        return await _rule_based_fallback(db, account_id)

    if not _saved:
        logger.warning("research agent did not call save_research_config — using rule-based fallback")
        return await _rule_based_fallback(db, account_id)

    config = _saved[0]
    config["last_run_at"] = datetime.now(UTC).isoformat()

    # Attach a stats snapshot for observability (re-use the data the agent already fetched)
    try:
        snapshot = json.loads(await get_overall_stats.ainvoke({"days": 90}))
        config["stats_snapshot"] = {
            "total_trades": snapshot.get("total_trades", 0),
            "win_rate": snapshot.get("win_rate", 0),
            "pnl": snapshot.get("pnl", 0),
        }
    except Exception:
        pass

    return config


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _count_closed_trades(db: AsyncSession, account_id: int) -> int:
    """Count only trades that actually executed (profit != 0 — excludes expired/cancelled orders)."""
    from sqlalchemy import func, select

    from db.models import Trade

    row = (
        await db.execute(
            select(func.count(Trade.id)).where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.profit != 0,
                Trade.exclude_from_research.is_not(True),
            )
        )
    ).scalar_one()
    return row or 0


async def _rule_based_fallback(db: AsyncSession, account_id: int) -> dict:
    """Gather stats and produce a rule-based config when the agent fails."""
    stats = await _gather_stats(db, account_id)
    result = _rule_based_review(stats)
    result["last_run_at"] = datetime.now(UTC).isoformat()
    result["stats_snapshot"] = {
        "total_trades": stats["overall"]["total"],
        "win_rate": stats["overall"]["win_rate"],
        "pnl": stats["overall"]["pnl"],
    }
    return result


async def _gather_stats(db: AsyncSession, account_id: int) -> dict:
    """Aggregate trading stats for the rule-based fallback path."""
    from sqlalchemy import func, select

    from db.models import AIJournal, Trade

    since = datetime.now(UTC) - timedelta(days=90)

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
                Trade.profit != 0,
            )
        )
    ).one()

    sym_rows = (
        await db.execute(
            select(
                Trade.symbol,
                func.count(Trade.id).label("n"),
                func.count(Trade.id).filter(Trade.profit > 0).label("w"),
                func.coalesce(func.sum(Trade.profit), 0.0).label("pnl"),
            )
            .where(Trade.account_id == account_id, Trade.closed_at.is_not(None), Trade.closed_at >= since, Trade.profit != 0)
            .group_by(Trade.symbol)
        )
    ).all()

    recent_trades = (
        await db.execute(
            select(Trade.trade_analysis, Trade.profit)
            .where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.trade_analysis.is_not(None),
                Trade.profit != 0,
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
        "signal_reliability": {
            s: round(c["correct"] / max(c["correct"] + c["wrong"], 1), 2)
            for s, c in sig_counts.items()
        },
        "high_conf_win_rate": round(high_conf_wins / high_conf_total, 3) if high_conf_total else None,
        "recent_loss_lessons": lessons_from_losses[:10],
    }


def _rule_based_review(stats: dict) -> dict:
    """Derive lessons from raw stats — used when the agent fails."""
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

    # Preserve lesson_history from previous runs — append new unique lessons
    existing_history: list[dict] = []
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH) as f:
                old = json.load(f)
            existing_history = old.get("lesson_history", [])
        except Exception:
            pass

    existing_texts = {e["lesson"] for e in existing_history}
    now_iso = datetime.now(UTC).isoformat()
    for lesson in config.get("lessons", []):
        if lesson not in existing_texts:
            existing_history.append({"lesson": lesson, "recorded_at": now_iso})
            existing_texts.add(lesson)

    config["lesson_history"] = existing_history

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


# ── Trust score + confidence gate modulation ───────────────────────────────────
#
# blocked_symbols/suggested_params (above) are LLM-produced and advisory-only —
# nothing in the trading pipeline reads them. symbol_trust_scores is computed
# here deterministically from raw win/loss counts and is what the confidence
# gate actually consults, via effective_confidence_threshold() below.

def _wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score confidence interval for a win rate.

    A conservative estimate of the true win rate given a small sample —
    unlike a raw win_rate, it naturally pulls toward 0.5 as n shrinks.
    """
    if n <= 0:
        return 0.5
    phat = wins / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return max(0.0, min(1.0, (center - margin) / denom))


def _trust_score_from_stats(wins: int, n: int, min_sample: int = TRUST_MIN_SAMPLE) -> float:
    """Blend the Wilson lower bound toward neutral 0.5 when the sample is small.

    At n=0 the score is exactly 0.5 (no opinion); at n>=min_sample it's the
    full Wilson lower bound. This avoids a small early sample swinging the
    confidence gate the way a raw win_rate over 20-30 trades could.
    """
    if n <= 0:
        return 0.5
    weight = min(n / min_sample, 1.0) if min_sample > 0 else 1.0
    wlb = _wilson_lower_bound(wins, n)
    return round(0.5 * (1 - weight) + wlb * weight, 3)


async def compute_symbol_trust_scores(
    db: AsyncSession, account_id: int, days: int = 90
) -> dict[str, float]:
    """Compute a per-symbol trust score in [0, 1] from closed-trade win/loss counts.

    0.5 = neutral (no strong opinion, usually due to an insufficient sample).
    Above 0.5 = research trusts this symbol; below 0.5 = research is skeptical.
    Used to modulate the confidence gate, never to hard-block a symbol.
    """
    from sqlalchemy import func, select

    from db.models import Trade

    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                Trade.symbol,
                func.count(Trade.id).label("n"),
                func.count(Trade.id).filter(Trade.profit > 0).label("wins"),
            )
            .where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.closed_at >= since,
                Trade.profit != 0,
            )
            .group_by(Trade.symbol)
        )
    ).all()
    return {r.symbol: _trust_score_from_stats(r.wins, r.n) for r in rows}


def get_symbol_trust_score(symbol: str) -> float:
    """Read the last-computed trust score for a symbol; 0.5 (neutral) if unknown."""
    return read_config().get("symbol_trust_scores", {}).get(symbol, 0.5)


def compute_effective_threshold(
    base_threshold: float,
    trust_score: float,
    *,
    sensitivity: float = TRUST_SENSITIVITY,
    min_threshold: float = TRUST_MIN_THRESHOLD,
    max_threshold: float = TRUST_MAX_THRESHOLD,
) -> float:
    """Nudge the confidence gate threshold by how much research trusts a symbol.

    trust_score > 0.5 (research likes this symbol) lowers the bar — more trades
    get through. trust_score < 0.5 raises it — only higher-conviction trades on
    a symbol research is skeptical of get through. Never blocks outright.
    """
    adjusted = base_threshold - (trust_score - 0.5) * sensitivity
    return max(min_threshold, min(max_threshold, adjusted))


def effective_confidence_threshold(symbol: str, base_threshold: float) -> float:
    """Convenience wrapper: reads the persisted trust score for `symbol` and
    returns the confidence-gate threshold to actually compare against."""
    return compute_effective_threshold(base_threshold, get_symbol_trust_score(symbol))
