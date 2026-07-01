"""Per-strategy run history and aggregate stats."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.strategies._crud import _get_or_404
from db.models import AIJournal, BacktestRun, Trade
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{strategy_id}/runs")
async def get_strategy_runs(strategy_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, strategy_id)
    result = await db.execute(
        select(AIJournal)
        .where(AIJournal.strategy_id == strategy_id)
        .order_by(AIJournal.created_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()
    return [
        {
            "id": r.id,
            "account_id": r.account_id,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "action": r.signal,
            "confidence": r.confidence,
            "reasoning": r.rationale,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in runs
    ]


@router.get("/{strategy_id}/stats")
async def get_strategy_stats(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return latest backtest stats + live trading stats for a strategy."""
    await _get_or_404(db, strategy_id)

    # Latest completed backtest run
    latest_bt = (await db.execute(
        select(BacktestRun)
        .where(BacktestRun.strategy_id == strategy_id)
        .where(BacktestRun.status == "completed")
        .order_by(desc(BacktestRun.created_at))
        .limit(1)
    )).scalar_one_or_none()

    # All closed live trades for this strategy
    closed_trades = (await db.execute(
        select(Trade)
        .where(Trade.strategy_id == strategy_id)
        .where(Trade.closed_at.is_not(None))
    )).scalars().all()

    backtest_stats = None
    if latest_bt:
        backtest_stats = {
            "win_rate": latest_bt.win_rate,
            "profit_factor": latest_bt.profit_factor,
            "total_trades": latest_bt.total_trades,
            "total_return_pct": latest_bt.total_return_pct,
            "max_drawdown_pct": latest_bt.max_drawdown_pct,
            "run_date": latest_bt.created_at.isoformat(),
            "symbol": latest_bt.symbol,
            "timeframe": latest_bt.timeframe,
        }

    live_stats = None
    if closed_trades:
        wins = [t for t in closed_trades if (t.profit or 0) > 0]
        total_pnl = sum((t.profit or 0) for t in closed_trades)
        live_stats = {
            "total_trades": len(closed_trades),
            "win_rate": round(len(wins) / len(closed_trades), 4),
            "total_pnl": round(total_pnl, 2),
        }

    return {"backtest": backtest_stats, "live": live_stats}
