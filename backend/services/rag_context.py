"""RAG Context Service — builds a performance history block injected into every LLM analysis call.

The context is structured SQL-queried data (NOT vector search).  It gives the LLM visibility
into its own historical performance so it can self-calibrate confidence and avoid repeat mistakes.

Sections (mirrors the Polymarket bot's 10-section design, adapted for MT5):
  1. Overall Performance
  2. Last 20 Closed Trades
  3. Signal / Indicator Reliability  (from trade_analysis JSON)
  4. Symbol Performance
  5. Timeframe Performance
  6. Confidence Calibration  (ai_journal.confidence vs profit outcome)
  7. Trading Session Patterns  (London / NY / Tokyo)
  8. Lessons from Recent Losses  (from trade_analysis JSON)
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.confidence import confidence_bucket as _confidence_bucket

logger = logging.getLogger(__name__)

# UTC hour boundaries for the three trading sessions plus their overlap window.
_TOKYO_SESSION_START_HOUR = 22
_LONDON_SESSION_START_HOUR = 7
_NY_SESSION_START_HOUR = 12
_NY_SESSION_END_HOUR = 17

# ── helpers ──────────────────────────────────────────────────────────────────

def _session_label(dt: datetime | None) -> str:
    """Map UTC hour to trading session name."""
    if dt is None:
        return "unknown"
    h = dt.hour
    if _TOKYO_SESSION_START_HOUR <= h or h < _LONDON_SESSION_START_HOUR:
        return "Tokyo"
    if _LONDON_SESSION_START_HOUR <= h < _NY_SESSION_START_HOUR:
        return "London"
    if _NY_SESSION_START_HOUR <= h < _NY_SESSION_END_HOUR:
        return "NY"
    return "overlap"


# ── main builder ─────────────────────────────────────────────────────────────

async def build_rag_context(
    db: AsyncSession,
    account_id: int,
    symbol: str,
    timeframe: str,
    lookback_days: int = 90,
) -> str:
    """Return a ~3-4K char context string about this account's historical performance.

    Returns empty string on any error so LLM calls are never blocked by context failures.
    """
    try:
        return await _build(db, account_id, symbol, timeframe, lookback_days)
    except Exception:
        logger.exception("rag_context build failed — proceeding without context")
        return ""


async def _build(
    db: AsyncSession,
    account_id: int,
    symbol: str,
    timeframe: str,
    lookback_days: int,
) -> str:
    from db.models import AIJournal, Trade  # local import to avoid circular deps

    since = datetime.now(UTC) - timedelta(days=lookback_days)
    lines: list[str] = ["=== TRADING PERFORMANCE CONTEXT ==="]

    # ── 1. Overall Performance ────────────────────────────────────────────────
    row = (
        await db.execute(
            select(
                func.count(Trade.id).label("total"),
                func.count(Trade.id)
                .filter(Trade.profit > 0)
                .label("wins"),
                func.coalesce(func.sum(Trade.profit), 0.0).label("pnl"),
                func.coalesce(func.avg(Trade.profit).filter(Trade.profit > 0), 0.0).label("avg_win"),
                func.coalesce(func.avg(Trade.profit).filter(Trade.profit < 0), 0.0).label("avg_loss"),
            ).where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.closed_at >= since,
            )
        )
    ).one()

    total, wins, pnl = row.total, row.wins, row.pnl
    losses = total - wins
    wr = (wins / total * 100) if total > 0 else 0.0
    lines.append(
        f"\n[1] Overall Performance (last {lookback_days}d)\n"
        f"  Trades: {total} | WR: {wr:.1f}% | P&L: {pnl:+.2f}\n"
        f"  Avg Win: {row.avg_win:+.2f} | Avg Loss: {row.avg_loss:+.2f} | "
        f"W/L: {wins}/{losses}"
    )

    # ── 2. Last 20 Closed Trades ──────────────────────────────────────────────
    recent = (
        await db.execute(
            select(Trade, AIJournal)
            .outerjoin(AIJournal, AIJournal.trade_id == Trade.id)
            .where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
            )
            .order_by(Trade.closed_at.desc())
            .limit(20)
        )
    ).all()

    trade_lines: list[str] = []
    for trade, journal in recent:
        outcome = "WIN" if (trade.profit or 0) > 0 else "LOSS"
        conf_str = f" conf={journal.confidence:.0%}" if journal else ""
        analysis_lesson = ""
        if trade.trade_analysis:
            try:
                ta = json.loads(trade.trade_analysis)
                if ta.get("lesson"):
                    analysis_lesson = f" | lesson: {ta['lesson'][:60]}"
            except Exception:
                pass
        trade_lines.append(
            f"  {outcome} {trade.symbol} {trade.direction} P&L={f'{trade.profit:+.2f}' if trade.profit is not None else 'N/A'}"
            f"{conf_str}{analysis_lesson}"
        )
    lines.append("\n[2] Last 20 Closed Trades (newest first)\n" + "\n".join(trade_lines))

    # ── 3. Signal / Indicator Reliability ────────────────────────────────────
    sig_counts: dict[str, dict[str, int]] = {}  # signal_name → {correct, wrong}
    for trade, _ in recent:
        if not trade.trade_analysis:
            continue
        try:
            ta = json.loads(trade.trade_analysis)
            for sig in ta.get("correct_signals", []):
                sig_counts.setdefault(sig, {"correct": 0, "wrong": 0})["correct"] += 1
            for sig in ta.get("wrong_signals", []):
                sig_counts.setdefault(sig, {"correct": 0, "wrong": 0})["wrong"] += 1
        except Exception:
            continue

    if sig_counts:
        sig_lines: list[str] = []
        for sig, counts in sorted(
            sig_counts.items(), key=lambda x: x[1]["correct"] / max(sum(x[1].values()), 1), reverse=True
        ):
            total_sig = counts["correct"] + counts["wrong"]
            pct = counts["correct"] / total_sig * 100
            flag = "✅" if pct >= 55 else "❌"
            sig_lines.append(f"  {sig}: {pct:.0f}% reliable {flag} ({total_sig} samples)")
        lines.append("\n[3] Signal Reliability\n" + "\n".join(sig_lines))
    else:
        lines.append("\n[3] Signal Reliability\n  No post-trade analysis data yet.")

    # ── 4. Symbol Performance ─────────────────────────────────────────────────
    sym_rows = (
        await db.execute(
            select(
                Trade.symbol,
                func.count(Trade.id).label("n"),
                func.count(Trade.id).filter(Trade.profit > 0).label("w"),
                func.coalesce(func.sum(Trade.profit), 0.0).label("pnl"),
            )
            .where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.closed_at >= since,
            )
            .group_by(Trade.symbol)
            .order_by(func.coalesce(func.sum(Trade.profit), 0.0).desc())
        )
    ).all()

    sym_lines = [
        f"  {r.symbol}: WR={r.w / r.n * 100:.0f}% n={r.n} P&L={r.pnl:+.2f}"
        + (" ← current" if r.symbol == symbol else "")
        for r in sym_rows
    ]
    lines.append("\n[4] Symbol Performance\n" + ("\n".join(sym_lines) or "  No data yet."))

    # ── 5. Timeframe Performance ──────────────────────────────────────────────
    tf_rows = (
        await db.execute(
            select(
                AIJournal.timeframe,
                func.count(Trade.id).label("n"),
                func.count(Trade.id).filter(Trade.profit > 0).label("w"),
                func.coalesce(func.sum(Trade.profit), 0.0).label("pnl"),
            )
            .join(Trade, AIJournal.trade_id == Trade.id)
            .where(
                Trade.account_id == account_id,
                Trade.closed_at.is_not(None),
                Trade.closed_at >= since,
            )
            .group_by(AIJournal.timeframe)
            .order_by(func.coalesce(func.sum(Trade.profit), 0.0).desc())
        )
    ).all()

    tf_lines = [
        f"  {r.timeframe}: WR={r.w / r.n * 100:.0f}% n={r.n} P&L={r.pnl:+.2f}"
        + (" ← current" if r.timeframe == timeframe else "")
        for r in tf_rows
    ]
    lines.append("\n[5] Timeframe Performance\n" + ("\n".join(tf_lines) or "  No data yet."))

    # ── 6. Confidence Calibration ─────────────────────────────────────────────
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

    buckets: dict[str, dict[str, int]] = {
        "very_high": {"wins": 0, "total": 0},
        "high": {"wins": 0, "total": 0},
        "medium": {"wins": 0, "total": 0},
        "low": {"wins": 0, "total": 0},
    }
    for conf, profit in cal_rows:
        b = _confidence_bucket(conf)
        if b in buckets:
            buckets[b]["total"] += 1
            if (profit or 0) > 0:
                buckets[b]["wins"] += 1

    cal_lines: list[str] = []
    labels = {"very_high": "≥80%", "high": "65-80%", "medium": "50-65%", "low": "<50%"}
    for b, lbl in labels.items():
        d = buckets[b]
        if d["total"] > 0:
            wr_b = d["wins"] / d["total"] * 100
            flag = " ← overconfident!" if b == "very_high" and wr_b < 50 else ""
            cal_lines.append(f"  {b.replace('_', ' ').title()} ({lbl}): {wr_b:.0f}% WR ({d['total']} trades){flag}")
    lines.append("\n[6] Confidence Calibration\n" + ("\n".join(cal_lines) or "  Not enough data yet."))

    # ── 7. Trading Session Patterns ───────────────────────────────────────────
    session_stats: dict[str, dict[str, int]] = {}
    for trade, _ in recent:
        s = _session_label(trade.opened_at)
        session_stats.setdefault(s, {"wins": 0, "total": 0})
        session_stats[s]["total"] += 1
        if (trade.profit or 0) > 0:
            session_stats[s]["wins"] += 1

    sess_lines = []
    for sess, d in session_stats.items():
        wr_s = d["wins"] / d["total"] * 100
        flag = " ← avoid" if wr_s < 40 and d["total"] >= 5 else (
            " ← best" if wr_s >= 60 and d["total"] >= 5 else ""
        )
        sess_lines.append(f"  {sess}: {wr_s:.0f}% WR ({d['total']} trades){flag}")
    lines.append("\n[7] Trading Session Patterns\n" + ("\n".join(sess_lines) or "  No data yet."))

    # ── 8. Lessons from Recent Losses ────────────────────────────────────────
    lessons: list[str] = []
    for trade, _ in recent:
        if (trade.profit or 0) >= 0:
            continue  # only losses
        if not trade.trade_analysis:
            continue
        try:
            ta = json.loads(trade.trade_analysis)
            lesson = ta.get("lesson", "").strip()
            if lesson:
                lessons.append(f"  • {lesson[:120]}")
        except Exception:
            continue
        if len(lessons) >= 5:
            break

    # also append research_config lessons if available
    try:
        import os
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "data", "research_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg = json.load(f)
            # Current-cycle lessons (latest run)
            for lesson in cfg.get("lessons", [])[:3]:
                lessons.append(f"  • [auto] {lesson[:120]}")
            # Historical lessons — 3 most recent unique ones not already shown
            shown = {line.strip(" •[auto]") for line in lessons}
            history = cfg.get("lesson_history", [])
            added = 0
            for entry in reversed(history):  # newest first
                text = entry.get("lesson", "").strip()
                if text and text not in shown and added < 3:
                    lessons.append(f"  • [history] {text[:120]}")
                    shown.add(text)
                    added += 1
    except Exception:
        pass

    lines.append("\n[8] Lessons from Recent Losses\n" + ("\n".join(lessons) or "  No lessons recorded yet."))

    lines.append("\n=== END PERFORMANCE CONTEXT ===")
    return "\n".join(lines)
