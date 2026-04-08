"""Context fetching for LLM pipeline.

Extracted from ai_trading.py:
  - Position context (open MT5 positions)
  - Recent signals (AIJournal entries)
  - Trade history + RAG context
  - News context
"""
import logging
import time
from typing import TYPE_CHECKING

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.models import Account, AIJournal
from mt5.bridge import AccountCredentials, MT5Bridge
from services.pipeline_tracer import PipelineTracer

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def fetch_open_positions(
    account: "Account",
    account_id: int,
    tracer: "PipelineTracer",
) -> list[dict]:
    """Fetch open MT5 positions for LLM context.

    Returns list of position dicts with symbol, direction, volume, profit.
    Returns [] on error. Records positions_fetched step in tracer.

    Args:
        account: Account ORM object with credentials
        account_id: Account ID for logging
        tracer: PipelineTracer for recording step

    Returns:
        List of position dicts, empty list on error
    """
    t0 = time.monotonic()
    open_positions: list[dict] = []
    try:
        pos_password = decrypt(account.password_encrypted)
        pos_creds = AccountCredentials(
            login=account.login,
            password=pos_password,
            server=account.server,
            path=account.mt5_path or settings.mt5_path,
        )
        async with MT5Bridge(pos_creds) as pos_bridge:
            raw_positions = await pos_bridge.get_positions()
        open_positions = [
            {
                "symbol": p.get("symbol", ""),
                "direction": "BUY" if p.get("type") == 0 else "SELL",
                "volume": p.get("volume", 0),
                "profit": p.get("profit", 0),
            }
            for p in raw_positions
        ]
    except Exception as exc:
        logger.warning(
            "Could not fetch positions for LLM context | account_id=%s: %s",
            account_id,
            exc,
        )
    await tracer.record(
        "positions_fetched",
        output_data={"positions": open_positions, "count": len(open_positions)},
        duration_ms=int((time.monotonic() - t0) * 1000),
    )
    return open_positions


async def fetch_recent_signals(
    account_id: int,
    symbol: str,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> list[dict]:
    """Fetch last 5 AIJournal entries for account+symbol.

    Returns list of signal dicts with symbol, signal, confidence, rationale (truncated).
    Returns [] on error. Records signals_fetched step in tracer.

    Args:
        account_id: Account ID
        symbol: Trading symbol
        db: SQLAlchemy AsyncSession
        tracer: PipelineTracer for recording step

    Returns:
        List of signal dicts, empty list on error
    """
    t0 = time.monotonic()
    recent_signals: list[dict] = []
    try:
        journal_rows = (
            await db.execute(
                select(AIJournal)
                .where(AIJournal.account_id == account_id, AIJournal.symbol == symbol)
                .order_by(desc(AIJournal.created_at))
                .limit(5)
            )
        ).scalars().all()
        recent_signals = [
            {
                "symbol": j.symbol,
                "signal": j.signal,
                "confidence": j.confidence,
                "rationale": j.rationale[:120],
            }
            for j in journal_rows
        ]
    except Exception as exc:
        logger.warning(
            "Could not fetch recent signals for LLM context | account_id=%s: %s",
            account_id,
            exc,
        )
    await tracer.record(
        "signals_fetched",
        output_data={"signals": recent_signals, "count": len(recent_signals)},
        duration_ms=int((time.monotonic() - t0) * 1000),
    )
    return recent_signals


async def build_trade_history_context(
    account: "Account",
    account_id: int,
    symbol: str,
    tf_upper: str,
    db: AsyncSession,
    tracer: "PipelineTracer",
) -> str | None:
    """Fetch MT5 trade history (30 days) + RAG context.

    Combines trade history from HistoryService with RAG performance context.
    Records rag_context step in tracer.

    Args:
        account: Account ORM object
        account_id: Account ID for logging
        symbol: Trading symbol
        tf_upper: Upper timeframe (e.g., "H4")
        db: SQLAlchemy AsyncSession
        tracer: PipelineTracer for recording step

    Returns:
        Combined context string, or None if both history and RAG fail
    """
    trade_history_context: str | None = None
    try:
        from services.history_sync import HistoryService

        hist_svc = HistoryService()
        recent_deals = await hist_svc.get_raw_deals(account, days=30)
        out_deals, in_by_pos = HistoryService._pair_deals(recent_deals)
        trade_history_context = (
            HistoryService.format_for_llm(out_deals, in_by_pos, limit=10) or None
        )
    except Exception as exc:
        logger.warning(
            "Could not fetch trade history for LLM context | account_id=%s: %s",
            account_id,
            exc,
        )

    # ── RAG Performance Context (self-calibration) ────────────────
    from services.rag_context import build_rag_context

    rag_ctx = await build_rag_context(db, account_id, symbol, tf_upper)
    await tracer.record(
        "rag_context",
        output_data={
            "has_context": rag_ctx is not None,
            "length": len(rag_ctx) if rag_ctx else 0,
        },
    )
    if rag_ctx:
        trade_history_context = (
            (trade_history_context + "\n\n" if trade_history_context else "")
            + rag_ctx
        )

    return trade_history_context


async def fetch_news_context(symbol: str) -> str | None:
    """Fetch news context for symbol if news is enabled in settings.

    Returns None if news is disabled or if fetching fails.

    Args:
        symbol: Trading symbol

    Returns:
        News context string, or None
    """
    if not getattr(settings, "news_enabled", False):
        return None

    try:
        from services.market_context import (
            fetch_upcoming_events,
            format_news_context,
        )

        events = await fetch_upcoming_events([symbol])
        news_context_str = format_news_context(events) or None
        return news_context_str
    except Exception as exc:
        logger.warning("Could not fetch news context for symbol=%s: %s", symbol, exc)
        return None
