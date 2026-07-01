"""Per-trade analytics: win/loss group breakdowns, heatmaps, indicator combinations."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BacktestRun, BacktestTrade, Strategy
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/runs/{run_id}/analytics")
async def get_analytics_summary(run_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    strategy = await db.get(Strategy, run.strategy_id)
    panel_type = "pattern_grid"   # default; override from strategy analytics_schema if available
    if strategy and strategy.module_path and strategy.class_name:
        try:
            import importlib
            mod = importlib.import_module(strategy.module_path)
            cls = getattr(mod, strategy.class_name)
            schema = cls().analytics_schema()
            panel_type = schema.get("panel_type", panel_type)
        except Exception:
            pass
    return {
        "run_id": run_id,
        "panel_type": panel_type,
        "total_trades": run.total_trades,
        "win_rate": run.win_rate,
        "profit_factor": run.profit_factor,
        "max_drawdown_pct": run.max_drawdown_pct,
        "sharpe_ratio": run.sharpe_ratio,
        "total_return_pct": run.total_return_pct,
    }


_ALLOWED_GROUP_BY = {"symbol", "pattern_name", "direction", "exit_reason"}
_ALLOWED_HEATMAP_AXES = {"symbol", "pattern_name", "direction"}
_ALLOWED_METRICS = {"win_rate", "total_pnl", "profit_factor"}


@router.get("/runs/{run_id}/analytics/groups")
async def get_analytics_groups(
    run_id: int,
    group_by: str = Query("pattern_name"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    if group_by not in _ALLOWED_GROUP_BY:
        raise HTTPException(400, f"group_by must be one of: {sorted(_ALLOWED_GROUP_BY)}")
    from services.backtest_analytics import aggregate_by_group
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    q = select(BacktestTrade).where(BacktestTrade.run_id == run_id)
    trades_orm = (await db.execute(q)).scalars().all()
    trades = [{"symbol": t.symbol, "pattern_name": t.pattern_name,
               "profit": t.profit, "direction": t.direction} for t in trades_orm]
    return aggregate_by_group(trades, group_by=group_by)


@router.get("/runs/{run_id}/analytics/heatmap")
async def get_analytics_heatmap(
    run_id: int,
    axis1: str = Query("symbol"),
    axis2: str = Query("pattern_name"),
    metric: str = Query("win_rate"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if axis1 not in _ALLOWED_HEATMAP_AXES or axis2 not in _ALLOWED_HEATMAP_AXES:
        raise HTTPException(400, f"axis1/axis2 must be one of: {sorted(_ALLOWED_HEATMAP_AXES)}")
    if metric not in _ALLOWED_METRICS:
        raise HTTPException(400, f"metric must be one of: {sorted(_ALLOWED_METRICS)}")
    from services.backtest_analytics import build_heatmap
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    q = select(BacktestTrade).where(BacktestTrade.run_id == run_id)
    trades_orm = (await db.execute(q)).scalars().all()
    trades = [{"symbol": t.symbol, "pattern_name": t.pattern_name, "profit": t.profit}
              for t in trades_orm]
    return build_heatmap(trades, axis1=axis1, axis2=axis2, metric=metric)


@router.get("/runs/{run_id}/analytics/combinations")
async def get_analytics_combinations(
    run_id: int,
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from services.backtest_analytics import (
        build_heatmap,
        generate_recommendations,
        get_top_combinations,
    )
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    q = select(BacktestTrade).where(BacktestTrade.run_id == run_id)
    trades_orm = (await db.execute(q)).scalars().all()
    trades = [{"symbol": t.symbol, "pattern_name": t.pattern_name, "profit": t.profit,
               "direction": t.direction} for t in trades_orm]
    combos = get_top_combinations(trades, limit=limit)
    heatmap = build_heatmap(trades, "symbol", "pattern_name", "win_rate")
    recs = generate_recommendations(heatmap, trades)
    return {**combos, "recommendations": recs}


# ── Background job ─────────────────────────────────────────────────────────────

