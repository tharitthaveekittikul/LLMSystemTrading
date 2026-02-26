from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Trade
from db.postgres import get_db

router = APIRouter()


@router.get("/summary")
async def get_summary(
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return institutional-grade trading metrics for closed trades."""
    query = select(Trade).where(Trade.closed_at != None)  # noqa: E711
    if account_id:
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
