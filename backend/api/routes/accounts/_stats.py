"""Aggregated trade stats, raw MT5 history, and equity-curve retrieval."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.accounts._schemas import AccountStatsResponse, EquityPoint
from db.models import Account
from db.postgres import get_db
from services.history_sync import HistoryService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{account_id}/stats", response_model=AccountStatsResponse)
async def get_account_stats(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return aggregated trade statistics for an account (closed trades only)."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from db.models import Trade

    result = await db.execute(
        select(
            func.count(Trade.id).label("trade_count"),
            func.coalesce(func.sum(Trade.profit), 0.0).label("total_pnl"),
            func.count(Trade.id).filter(Trade.profit > 0).label("winning_trades"),
        ).where(
            Trade.account_id == account_id,
            Trade.closed_at.is_not(None),
        )
    )
    row = result.one()
    trade_count = row.trade_count or 0
    winning_trades = row.winning_trades or 0
    win_rate = winning_trades / trade_count if trade_count > 0 else 0.0

    return AccountStatsResponse(
        win_rate=round(win_rate, 4),
        total_pnl=round(float(row.total_pnl), 2),
        trade_count=trade_count,
        winning_trades=winning_trades,
    )


@router.get("/{account_id}/history", response_model=list[dict])
async def get_account_history(
    account_id: int,
    days: int = Query(90, ge=1, le=3650, description="Number of days of history to fetch"),
    db: AsyncSession = Depends(get_db),
):
    """Return raw MT5 closed deals for the last N days.

    Each item is one deal dict from MT5. Use this for dashboard charts and analytics.
    Errors: 404 account not found, 502/503 MT5 unavailable.
    """
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    logger.info("Fetching MT5 history | account_id=%s days=%s", account_id, days)
    try:
        svc = HistoryService()
        deals = await svc.get_raw_deals(account, days)
    except RuntimeError as exc:
        logger.error("MT5 unavailable (history) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        logger.error("MT5 connect failed (history) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return deals

@router.get("/{account_id}/equity-history", response_model=list[EquityPoint])
async def get_equity_history(
    account_id: int,
    hours: int = Query(24, ge=0, le=8760),
    db: AsyncSession = Depends(get_db),
):
    """Return equity snapshots for the last N hours (default 24). Empty list if QuestDB unavailable."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from db.questdb import get_equity_history
    points = await get_equity_history(account_id=account_id, hours=hours)
    return points


