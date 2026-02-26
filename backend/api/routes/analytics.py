import logging
from datetime import date
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import cast, Date, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Trade
from db.postgres import get_db

logger = logging.getLogger(__name__)


class DailyEntry(BaseModel):
    date: date
    net_pnl: float
    trade_count: int


class DailyPnLResponse(BaseModel):
    year: int
    month: int
    account_id: int | None
    days: list[DailyEntry]
    monthly_total: float
    monthly_trade_count: int
    winning_days: int
    losing_days: int


router = APIRouter()


@router.get("/summary")
async def get_summary(
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return institutional-grade trading metrics for closed trades."""
    query = select(Trade).where(Trade.closed_at != None)  # noqa: E711
    if account_id is not None:
        query = query.where(Trade.account_id == account_id)

    result = await db.execute(query)
    trades = result.scalars().all()

    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_profit": 0.0,
            "max_drawdown": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }

    profits = [t.profit or 0.0 for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    win_rate = len(wins) / len(profits) if profits else 0.0

    # Simple max drawdown from equity curve
    max_drawdown = _calculate_max_drawdown(profits)

    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 2),
        "total_profit": round(sum(profits), 2),
        "max_drawdown": round(max_drawdown, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
    }


@router.get("/daily", response_model=DailyPnLResponse)
async def get_daily_pnl(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return per-day aggregated PnL for a given month.

    Only closed trades (closed_at IS NOT NULL) are included.
    Days with no closed trades are not returned (sparse list).
    """
    date_col = cast(Trade.closed_at, Date)

    query = (
        select(
            date_col.label("date"),
            func.sum(Trade.profit).label("net_pnl"),
            func.count(Trade.id).label("trade_count"),
        )
        .where(Trade.closed_at != None)  # noqa: E711
        .where(extract("year", Trade.closed_at) == year)
        .where(extract("month", Trade.closed_at) == month)
        .group_by(date_col)
        .order_by(date_col)
    )
    if account_id is not None:
        query = query.where(Trade.account_id == account_id)

    result = await db.execute(query)
    rows = result.all()

    days = [
        DailyEntry(
            date=row.date,
            net_pnl=round(row.net_pnl or 0.0, 2),
            trade_count=row.trade_count,
        )
        for row in rows
    ]

    monthly_total = round(sum(d.net_pnl for d in days), 2)
    monthly_trade_count = sum(d.trade_count for d in days)
    winning_days = sum(1 for d in days if d.net_pnl > 0)
    losing_days = sum(1 for d in days if d.net_pnl < 0)

    return DailyPnLResponse(
        year=year,
        month=month,
        account_id=account_id,
        days=days,
        monthly_total=monthly_total,
        monthly_trade_count=monthly_trade_count,
        winning_days=winning_days,
        losing_days=losing_days,
    )


def _calculate_max_drawdown(profits: list[float]) -> float:
    """Calculate max drawdown as absolute value from running equity curve."""
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for p in profits:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd
