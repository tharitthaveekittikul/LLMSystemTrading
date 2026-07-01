"""Research-loop cycle progress: view, manually trigger, and exclude trades."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.accounts._schemas import ResearchCycleTrade, ResearchProgressResponse
from db.models import Account, Trade
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{account_id}/research-progress", response_model=ResearchProgressResponse)
async def get_research_progress(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return the current 30-trade research loop progress for an account."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from services.research_loop import RESEARCH_EVERY, _count_closed_trades, read_config
    closed_trades = await _count_closed_trades(db, account_id)
    config = read_config()
    last_run_at: str | None = config.get("last_run_at")
    last_run_count: int = config.get("trade_count_at_run", 0)
    cycle_progress = max(closed_trades - last_run_count, 0)  # clamp: old configs may have stored total count
    remaining = max(RESEARCH_EVERY - cycle_progress, 0)
    just_completed = cycle_progress == 0 and last_run_at is not None

    # Fetch trades in the current cycle (since last successful run)
    last_trade_id_at_run: int = config.get("last_trade_id_at_run", 0)
    cycle_trades: list[ResearchCycleTrade] = []
    if cycle_progress > 0 or last_trade_id_at_run:
        from sqlalchemy import select

        from db.models import Trade
        base_where = [Trade.account_id == account_id, Trade.closed_at.is_not(None), Trade.profit != 0]
        if last_trade_id_at_run:
            base_where.append(Trade.id > last_trade_id_at_run)
        rows = (
            await db.execute(
                select(Trade.id, Trade.symbol, Trade.direction, Trade.profit, Trade.closed_at, Trade.exclude_from_research)
                .where(*base_where)
                .order_by(Trade.closed_at.desc())
                .limit(cycle_progress if not last_trade_id_at_run else None)
            )
        ).all()
        cycle_trades = [
            ResearchCycleTrade(
                id=r.id,
                symbol=r.symbol,
                direction=r.direction or "—",
                profit=float(r.profit or 0),
                closed_at=r.closed_at.isoformat() if r.closed_at else None,
                excluded=bool(r.exclude_from_research),
            )
            for r in rows
        ]

    return ResearchProgressResponse(
        closed_trades=closed_trades,
        cycle_progress=cycle_progress,
        remaining=remaining,
        last_run_at=last_run_at,
        just_completed=just_completed,
        cycle_trades=cycle_trades,
    )


@router.post("/{account_id}/research-loop/trigger", status_code=200)
async def trigger_research_loop(account_id: int, db: AsyncSession = Depends(get_db)):
    """Manually trigger the research loop for an account (forced run)."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from services.research_loop import run
    try:
        await run(account_id, db)
        from services.research_loop import read_config
        config = read_config()
        return {"status": "ok", "last_run_at": config.get("last_run_at")}
    except Exception as exc:
        logger.exception("Manual research loop trigger failed | account_id=%s", account_id)
        raise HTTPException(status_code=500, detail=f"Research loop failed: {exc}") from exc


@router.post("/{account_id}/research-progress/trades/{trade_id}/toggle-exclude", status_code=200)
async def toggle_exclude_research_trade(account_id: int, trade_id: int, db: AsyncSession = Depends(get_db)):
    """Toggle exclude_from_research flag on a trade. Excluded trades are skipped by the research loop."""
    trade = await db.get(Trade, trade_id)
    if not trade or trade.account_id != account_id:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade.exclude_from_research = not trade.exclude_from_research
    await db.commit()
    return {"id": trade_id, "excluded": trade.exclude_from_research}


# ── Helpers ───────────────────────────────────────────────────────────────────


