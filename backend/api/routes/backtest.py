"""Backtest API — submit runs, poll status, retrieve results."""
from __future__ import annotations

import importlib
import io
import json
import logging
import tempfile
from datetime import datetime, UTC

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.ws import broadcast_all
from db.models import BacktestRun, BacktestTrade, Strategy, Account
from db.postgres import get_db, AsyncSessionLocal
from services.backtest_data import BacktestDataService, BacktestDataError
from services.backtest_engine import BacktestEngine
from services.backtest_metrics import compute_metrics, compute_monthly_pnl

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class BacktestRunRequest(BaseModel):
    strategy_id: int
    symbol: str = Field(..., min_length=1, max_length=20)
    timeframe: str | None = Field(default=None)  # None → use strategy's primary_tf
    start_date: datetime
    end_date: datetime
    initial_balance: float = Field(default=10_000.0, gt=0)
    spread_pips: float = Field(default=1.5, ge=0)
    execution_mode: str = Field(default="close_price")
    max_llm_calls: int = Field(default=100, ge=0)
    volume: float = Field(default=0.1, gt=0)
    risk_pct: float | None = Field(default=None, ge=0, le=1)  # e.g. 0.01 = 1%; None = fixed lot
    csv_upload_id: str | None = None          # primary TF CSV (backward compat)
    csv_uploads: dict[str, str] | None = None  # {tf_name: upload_id} for MTF CSVs


class BacktestRunSummary(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float
    spread_pips: float
    execution_mode: str
    status: str
    progress_pct: int
    error_message: str | None
    total_trades: int | None
    win_rate: float | None
    profit_factor: float | None
    expectancy: float | None
    max_drawdown_pct: float | None
    recovery_factor: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    total_return_pct: float | None
    avg_win: float | None
    avg_loss: float | None
    max_consec_wins: int | None
    max_consec_losses: int | None
    avg_spread: float | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, r: BacktestRun) -> "BacktestRunSummary":
        return cls(
            id=r.id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            timeframe=r.timeframe,
            start_date=r.start_date.isoformat(),
            end_date=r.end_date.isoformat(),
            initial_balance=r.initial_balance,
            spread_pips=r.spread_pips,
            execution_mode=r.execution_mode,
            status=r.status,
            progress_pct=r.progress_pct,
            error_message=r.error_message,
            total_trades=r.total_trades,
            win_rate=r.win_rate,
            profit_factor=r.profit_factor,
            expectancy=r.expectancy,
            max_drawdown_pct=r.max_drawdown_pct,
            recovery_factor=r.recovery_factor,
            sharpe_ratio=r.sharpe_ratio,
            sortino_ratio=r.sortino_ratio,
            total_return_pct=r.total_return_pct,
            avg_win=r.avg_win,
            avg_loss=r.avg_loss,
            max_consec_wins=r.max_consec_wins,
            max_consec_losses=r.max_consec_losses,
            avg_spread=r.avg_spread,
            created_at=r.created_at.isoformat(),
        )


class BacktestTradeOut(BaseModel):
    id: int
    run_id: int
    symbol: str
    direction: str
    entry_time: str
    exit_time: str | None
    entry_price: float
    exit_price: float | None
    stop_loss: float
    take_profit: float
    volume: float
    profit: float | None
    exit_reason: str | None
    equity_after: float | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, t: BacktestTrade) -> "BacktestTradeOut":
        return cls(
            id=t.id,
            run_id=t.run_id,
            symbol=t.symbol,
            direction=t.direction,
            entry_time=t.entry_time.isoformat(),
            exit_time=t.exit_time.isoformat() if t.exit_time else None,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            stop_loss=t.stop_loss,
            take_profit=t.take_profit,
            volume=t.volume,
            profit=t.profit,
            exit_reason=t.exit_reason,
            equity_after=t.equity_after,
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

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

    # Compute avg spread for display in the UI (informational only — never fail upload)
    avg_spread_pts: float | None = None
    try:
        from services.backtest_data import BacktestDataService
        svc = BacktestDataService()
        candles = await svc.load_from_csv(_io.StringIO(content.decode("utf-8", errors="replace")))
        spreads = [c["spread"] for c in candles if c.get("spread", 0) > 0]
        if spreads:
            avg_spread_pts = round(sum(spreads) / len(spreads), 1)
    except Exception:
        pass  # avg_spread is informational — never fail the upload for it

    logger.info(
        "CSV uploaded: %s (%d bytes, avg_spread=%.1f pts)",
        tmp_path, len(content), avg_spread_pts or 0,
    )
    return {"upload_id": tmp_path, "size_bytes": len(content), "avg_spread_pts": avg_spread_pts}


# ── Analytics endpoints ────────────────────────────────────────────────────────

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
    from services.backtest_analytics import get_top_combinations, generate_recommendations, build_heatmap
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

async def _run_backtest_job(
    run_id: int,
    req: BacktestRunRequest,
    strategy_db: Strategy,
    timeframe: str,
    context_tfs: list[str],
) -> None:
    """Background task: load OHLCV data, run engine, persist results."""
    async with AsyncSessionLocal() as db:
        run = await db.get(BacktestRun, run_id)
        if not run:
            return

        run.status = "running"
        await db.commit()
        await broadcast_all("backtest_progress", {"run_id": run_id, "progress_pct": 0})

        try:
            # ── Load OHLCV data ────────────────────────────────────────────────
            data_svc = BacktestDataService()

            if req.csv_upload_id or req.csv_uploads:
                # ── CSV path (primary TF) ──────────────────────────────────────
                primary_upload = req.csv_upload_id or (
                    req.csv_uploads.get(timeframe) if req.csv_uploads else None
                )
                if not primary_upload:
                    raise BacktestDataError(
                        "No primary-TF CSV provided. Upload a CSV for the primary timeframe."
                    )
                with open(primary_upload, "r") as f:
                    candles = await data_svc.load_from_csv(io.StringIO(f.read()))

                # ── Context TF CSVs (optional) ─────────────────────────────────
                context_candles: dict[str, list[dict]] = {}
                if req.csv_uploads:
                    for ctx_tf, upload_path in req.csv_uploads.items():
                        if ctx_tf == timeframe:
                            continue  # already loaded as primary
                        with open(upload_path, "r") as f:
                            ctx_c = await data_svc.load_from_csv(io.StringIO(f.read()))
                        context_candles[ctx_tf] = ctx_c
                        logger.info(
                            "Loaded context TF %s: %d candles", ctx_tf, len(ctx_c)
                        )
            else:
                from mt5.bridge import MT5Bridge, AccountCredentials, MT5_AVAILABLE
                if not MT5_AVAILABLE:
                    raise BacktestDataError(
                        "MT5 is not available. Please upload a CSV file instead."
                    )
                account = (await db.execute(
                    select(Account).where(Account.is_active == True).limit(1)  # noqa: E712
                )).scalars().first()
                if not account:
                    raise BacktestDataError("No active MT5 account found")
                from core.security import decrypt
                creds = AccountCredentials(
                    login=account.login,
                    password=decrypt(account.password_encrypted),
                    server=account.server,
                    path=account.mt5_path or "",
                )
                # Primary TF
                tf_int = _timeframe_to_int(timeframe)
                async with MT5Bridge(creds) as bridge:
                    candles = await data_svc.load_from_mt5(
                        bridge, req.symbol, tf_int, req.start_date, req.end_date
                    )
                # Context TFs from MT5 (auto-loaded when available)
                context_candles = {}
                async with MT5Bridge(creds) as bridge:
                    for ctx_tf in context_tfs:
                        try:
                            ctx_c = await data_svc.load_from_mt5(
                                bridge, req.symbol, _timeframe_to_int(ctx_tf),
                                req.start_date, req.end_date,
                            )
                            context_candles[ctx_tf] = ctx_c
                            logger.info("Loaded MT5 context TF %s: %d candles", ctx_tf, len(ctx_c))
                        except Exception as exc:
                            logger.warning("Could not load context TF %s: %s", ctx_tf, exc)

            # ── Load strategy instance ─────────────────────────────────────────
            strategy_instance = _load_strategy(strategy_db)

            # ── Run engine ────────────────────────────────────────────────────
            engine = BacktestEngine()
            config = {
                "symbol": req.symbol,
                "timeframe": timeframe,
                "initial_balance": req.initial_balance,
                "spread_pips": req.spread_pips,
                "execution_mode": req.execution_mode,
                "volume": req.volume,
                "risk_pct": req.risk_pct,
                "max_llm_calls": req.max_llm_calls,
            }

            async def _progress(pct: int) -> None:
                async with AsyncSessionLocal() as progress_db:
                    r = await progress_db.get(BacktestRun, run_id)
                    if r:
                        r.progress_pct = pct
                        await progress_db.commit()
                await broadcast_all("backtest_progress", {"run_id": run_id, "progress_pct": pct})

            result = await engine.run(
                candles, strategy_instance, config,
                progress_cb=_progress,
                context_candles=context_candles or None,
            )
            run.avg_spread = result.get("avg_spread")

            # ── Persist trades ────────────────────────────────────────────────
            for td in result["trades"]:
                bt = BacktestTrade(
                    run_id=run_id,
                    symbol=td["symbol"],
                    direction=td["direction"],
                    entry_time=td["entry_time"],
                    exit_time=td.get("exit_time"),
                    entry_price=td["entry_price"],
                    exit_price=td.get("exit_price"),
                    stop_loss=td["stop_loss"],
                    take_profit=td["take_profit"],
                    volume=td["volume"],
                    profit=td.get("profit"),
                    exit_reason=td.get("exit_reason"),
                    equity_after=td.get("equity_after"),
                    pattern_name=td.get("pattern_name"),
                    pattern_metadata=json.dumps(td.get("pattern_metadata")) if td.get("pattern_metadata") else None,
                )
                db.add(bt)
            await db.flush()

            # ── Compute + persist metrics ──────────────────────────────────────
            closed = [t for t in result["trades"] if t.get("profit") is not None]
            metrics = compute_metrics(closed, req.initial_balance)

            run.status = "completed"
            run.progress_pct = 100
            run.total_trades = metrics["total_trades"]
            run.win_rate = metrics["win_rate"]
            run.profit_factor = metrics["profit_factor"]
            run.expectancy = metrics["expectancy"]
            run.max_drawdown_pct = metrics["max_drawdown_pct"]
            run.recovery_factor = metrics["recovery_factor"]
            run.sharpe_ratio = metrics["sharpe_ratio"]
            run.sortino_ratio = metrics["sortino_ratio"]
            run.total_return_pct = metrics["total_return_pct"]
            run.avg_win = metrics["avg_win"]
            run.avg_loss = metrics["avg_loss"]
            run.max_consec_wins = metrics["max_consec_wins"]
            run.max_consec_losses = metrics["max_consec_losses"]
            await db.commit()

            await broadcast_all("backtest_complete", {
                "run_id": run_id,
                "total_trades": metrics["total_trades"],
                "win_rate": metrics["win_rate"],
                "profit_factor": metrics["profit_factor"],
            })
            logger.info("Backtest run %d completed | %d trades", run_id, metrics["total_trades"])

        except Exception as exc:
            logger.error("Backtest run %d failed: %s", run_id, exc, exc_info=True)
            run.status = "failed"
            run.error_message = str(exc)[:500]
            await db.commit()
            await broadcast_all("backtest_failed", {"run_id": run_id, "error": str(exc)[:200]})


# ── Helpers ────────────────────────────────────────────────────────────────────

_CODE_MODES = {"rule_only", "rule_then_llm", "hybrid_validator", "multi_agent"}


def _load_strategy(strategy_db: Strategy):
    """Instantiate a strategy from the DB record."""
    if (
        (strategy_db.strategy_type == "code" or strategy_db.execution_mode in _CODE_MODES)
        and strategy_db.module_path
        and strategy_db.class_name
    ):
        mod = importlib.import_module(strategy_db.module_path)
        cls = getattr(mod, strategy_db.class_name)
        instance = cls()
        instance.strategy_type = "code"
        # Hydrate primary_tf, context_tfs, symbols from DB
        if hasattr(instance, "apply_db_config"):
            instance.apply_db_config(strategy_db)
        return instance

    class _ConfigStrategy:
        strategy_type = strategy_db.strategy_type
        _prompt = strategy_db.custom_prompt

        def generate_signal(self, market_data: dict) -> dict | None:
            return None  # triggers LLM path (sampled by engine)

        def system_prompt(self) -> str | None:
            return self._prompt

    return _ConfigStrategy()


def _timeframe_to_int(tf: str) -> int:
    mapping = {
        "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5,
        "M6": 6, "M10": 10, "M12": 12, "M15": 15, "M20": 20,
        "M30": 30, "H1": 16385, "H2": 16386, "H3": 16387,
        "H4": 16388, "H6": 16390, "H8": 16392, "H12": 16396,
        "D1": 16408, "W1": 32769, "MN1": 49153,
    }
    return mapping.get(tf.upper(), 15)
