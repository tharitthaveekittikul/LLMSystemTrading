"""Backtest run CRUD, data upload, and basic result retrieval (equity/drawdown/candles/monthly-pnl)."""
from __future__ import annotations

import json
import logging
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.backtest._execution import _run_backtest_job
from api.routes.backtest._schemas import BacktestRunRequest, BacktestRunSummary, BacktestTradeOut
from db.models import BacktestRun, BacktestTrade, Strategy
from db.postgres import get_db
from services.backtest_data import BacktestDataService
from services.backtest_metrics import compute_monthly_pnl

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/runs", response_model=BacktestRunSummary, status_code=202)
async def submit_run(
    req: BacktestRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> BacktestRunSummary:
    """Submit a new backtest job. Returns immediately with run_id; job runs in background."""
    strategy = await db.get(Strategy, req.strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if req.execution_mode not in ("close_price", "intra_candle"):
        raise HTTPException(
            status_code=422,
            detail="execution_mode must be 'close_price' or 'intra_candle'",
        )

    # Use strategy's primary_tf from DB as the canonical timeframe
    timeframe = req.timeframe or strategy.primary_tf or strategy.timeframe or "M15"
    context_tfs: list[str] = json.loads(strategy.context_tfs or "[]")

    run = BacktestRun(
        strategy_id=req.strategy_id,
        symbol=req.symbol,
        timeframe=timeframe,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_balance=req.initial_balance,
        spread_pips=req.spread_pips,
        execution_mode=req.execution_mode,
        max_llm_calls=req.max_llm_calls,
        commission_per_lot=req.commission_per_lot,
        tp_partial_close_ratio=req.tp_partial_close_ratio,
        status="pending",
        progress_pct=0,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    background_tasks.add_task(
        _run_backtest_job,
        run_id=run.id,
        req=req,
        strategy_db=strategy,
        timeframe=timeframe,
        context_tfs=context_tfs,
    )
    logger.info(
        "Backtest run %d submitted | strategy=%s symbol=%s",
        run.id, strategy.name, run.symbol,
    )
    return BacktestRunSummary.from_orm(run)


@router.get("/runs", response_model=list[BacktestRunSummary])
async def list_runs(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[BacktestRunSummary]:
    q = (
        select(BacktestRun)
        .order_by(desc(BacktestRun.created_at))
        .limit(limit)
        .offset(offset)
    )
    runs = (await db.execute(q)).scalars().all()
    return [BacktestRunSummary.from_orm(r) for r in runs]


@router.get("/runs/{run_id}", response_model=BacktestRunSummary)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)) -> BacktestRunSummary:
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return BacktestRunSummary.from_orm(run)


@router.get("/runs/{run_id}/trades", response_model=list[BacktestTradeOut])
async def get_trades(
    run_id: int,
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[BacktestTradeOut]:
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    q = (
        select(BacktestTrade)
        .where(BacktestTrade.run_id == run_id)
        .order_by(BacktestTrade.entry_time)
        .limit(limit)
        .offset(offset)
    )
    trades = (await db.execute(q)).scalars().all()
    return [BacktestTradeOut.from_orm(t) for t in trades]


@router.get("/runs/{run_id}/equity-curve")
async def get_equity_curve(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return [{time, equity}] for chart rendering."""
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    q = (
        select(BacktestTrade.exit_time, BacktestTrade.equity_after)
        .where(BacktestTrade.run_id == run_id)
        .where(BacktestTrade.exit_time.is_not(None))
        .order_by(BacktestTrade.exit_time)
    )
    rows = (await db.execute(q)).all()
    return [{"time": r.exit_time.isoformat(), "equity": r.equity_after} for r in rows]


@router.get("/runs/{run_id}/drawdown")
async def get_drawdown(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return [{time, drawdown_pct}] computed from the equity curve.

    Drawdown = (running_peak - current_equity) / running_peak * 100
    Returns positive drawdown percentage (0 = no drawdown, 20 = 20% below peak).
    """
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    q = (
        select(BacktestTrade.exit_time, BacktestTrade.equity_after)
        .where(BacktestTrade.run_id == run_id)
        .where(BacktestTrade.exit_time.is_not(None))
        .where(BacktestTrade.equity_after.is_not(None))
        .order_by(BacktestTrade.exit_time)
    )
    rows = (await db.execute(q)).all()
    if not rows:
        return []
    peak = run.initial_balance
    points = []
    for r in rows:
        equity = r.equity_after
        if equity > peak:
            peak = equity
        drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
        points.append({
            "time": r.exit_time.isoformat(),
            "drawdown_pct": round(drawdown_pct, 2),
        })
    return points


@router.get("/runs/{run_id}/candles")
async def get_candles(
    run_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return OHLCV candles for a backtest run (enables chart replay).

    CSV runs: reads the stored file at run.data_file_path.
    MT5 runs: not yet supported — returns 404.
    Response shape: [{time, open, high, low, close, volume}]
    """
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if not run.data_file_path:
        raise HTTPException(status_code=404, detail="No candle data stored for this run (MT5 runs not yet supported)")

    import pathlib
    p = pathlib.Path(run.data_file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Candle data file not found on disk")

    import io as _io

    svc = BacktestDataService()
    raw = await svc.load_from_csv(_io.StringIO(p.read_text(encoding="utf-8", errors="replace")))
    return [
        {
            "time": int(c["time"].timestamp()),
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c.get("tick_volume", 0),
        }
        for c in raw
    ]


@router.get("/runs/{run_id}/monthly-pnl")
async def get_monthly_pnl(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return [{year, month, pnl, trade_count}] for the monthly heatmap."""
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    q = (
        select(BacktestTrade)
        .where(BacktestTrade.run_id == run_id)
        .where(BacktestTrade.exit_time.is_not(None))
        .order_by(BacktestTrade.exit_time)
    )
    trades = (await db.execute(q)).scalars().all()
    trade_dicts = [{"profit": t.profit, "exit_time": t.exit_time} for t in trades]
    return compute_monthly_pnl(trade_dicts)


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: int, db: AsyncSession = Depends(get_db)) -> None:
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    await db.delete(run)
    await db.commit()


@router.post("/data/upload")
async def upload_csv(file: UploadFile = File(...)) -> dict:
    """Save uploaded CSV to temp file, return upload_id + avg_spread_pts for display."""
    import io as _io
    suffix = ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="wb") as f:
        content = await file.read()
        f.write(content)
        tmp_path = f.name

    # Compute avg spread and date range from the CSV (informational — never fail upload)
    avg_spread_pts: float | None = None
    start_date_str: str | None = None
    end_date_str: str | None = None
    try:
        from services.backtest_data import BacktestDataService
        svc = BacktestDataService()
        candles = await svc.load_from_csv(_io.StringIO(content.decode("utf-8", errors="replace")))
        spreads = [c["spread"] for c in candles if c.get("spread", 0) > 0]
        if spreads:
            avg_spread_pts = round(sum(spreads) / len(spreads), 1)
        # Extract date range from raw text (format: YYYY.MM.DD\t...)
        lines = content.decode("utf-8", errors="replace").splitlines()
        data_lines = [line for line in lines if line.strip() and not line.startswith("<")]
        if data_lines:
            start_date_str = data_lines[0].split("\t")[0].replace(".", "-")
            end_date_str = data_lines[-1].split("\t")[0].replace(".", "-")
    except Exception:
        pass  # all fields are informational — never fail the upload

    logger.info(
        "CSV uploaded: %s (%d bytes, avg_spread=%.1f pts, %s → %s)",
        tmp_path, len(content), avg_spread_pts or 0, start_date_str, end_date_str,
    )
    return {
        "upload_id": tmp_path,
        "size_bytes": len(content),
        "avg_spread_pts": avg_spread_pts,
        "start_date": start_date_str,
        "end_date": end_date_str,
    }


# ── Analytics endpoints ────────────────────────────────────────────────────────

