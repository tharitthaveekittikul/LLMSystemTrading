"""Grid-search optimization runs: submit, list, cancel, resume, and read results."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import OptimizationRun, Strategy
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Optimization schemas ──────────────────────────────────────────────────────

class OptimizationRequest(BaseModel):
    strategy_id: int
    symbol: str = Field(..., min_length=1, max_length=20)
    timeframe: str | None = Field(default=None)
    start_date: datetime
    end_date: datetime
    initial_balance: float = Field(default=10_000.0, gt=0)
    spread_pips: float = Field(default=1.5, ge=0)
    execution_mode: str = Field(default="close_price")
    volume: float = Field(default=0.1, gt=0)
    risk_pct: float | None = Field(default=None, ge=0, le=1)  # None=fixed lot; e.g. 0.01=1%
    commission_per_lot: float = Field(default=0.0, ge=0)
    tp_partial_close_ratio: float = Field(default=0.5, gt=0, le=1)
    max_workers: int = Field(default=4, ge=1, le=16)
    csv_upload_id: str | None = None
    csv_uploads: dict[str, str] | None = None
    param_grid: dict[str, list] = Field(..., description="Search space: {param_name: [v1, v2, ...]}")
    optimize_metric: str = Field(default="sharpe_ratio")


class OptimizationRunOut(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float
    spread_pips: float
    execution_mode: str
    volume: float
    risk_pct: float | None
    commission_per_lot: float
    tp_partial_close_ratio: float
    max_workers: int
    param_grid: dict
    optimize_metric: str
    status: str
    progress_pct: int
    total_combinations: int
    completed_combinations: int
    started_at: str | None
    completed_at: str | None
    elapsed_seconds: float | None
    estimated_seconds_remaining: float | None
    error_message: str | None
    # results omitted here — use GET /optimize/{id}/results for paginated access
    best_params: dict | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, r: OptimizationRun) -> "OptimizationRunOut":
        # Compute elapsed time
        elapsed_seconds: float | None = None
        if r.started_at:
            end = r.completed_at if r.completed_at else datetime.now(UTC)
            elapsed_seconds = (end - r.started_at).total_seconds()

        # Compute ETA from started_at + rate of completed combos
        eta: float | None = None
        if (
            r.started_at
            and r.status in ("running", "cancelling")
            and r.completed_combinations > 0
            and r.total_combinations > r.completed_combinations
            and elapsed_seconds
        ):
            rate = r.completed_combinations / elapsed_seconds if elapsed_seconds > 0 else None
            if rate:
                remaining = r.total_combinations - r.completed_combinations
                eta = remaining / rate

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
            volume=r.volume,
            risk_pct=r.risk_pct,
            commission_per_lot=r.commission_per_lot,
            tp_partial_close_ratio=r.tp_partial_close_ratio,
            max_workers=r.max_workers,
            param_grid=json.loads(r.param_grid or "{}"),
            optimize_metric=r.optimize_metric,
            status=r.status,
            progress_pct=r.progress_pct,
            total_combinations=r.total_combinations,
            completed_combinations=r.completed_combinations,
            started_at=r.started_at.isoformat() if r.started_at else None,
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            elapsed_seconds=elapsed_seconds,
            estimated_seconds_remaining=eta,
            error_message=r.error_message,
            best_params=json.loads(r.best_params or "{}") if r.best_params else None,
            created_at=r.created_at.isoformat(),
        )


# ── Optimization endpoints ─────────────────────────────────────────────────────

@router.post("/optimize", response_model=OptimizationRunOut, status_code=202)
async def submit_optimization(
    req: OptimizationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> OptimizationRunOut:
    """Submit a parameter sweep job. Returns immediately; optimization runs in background."""
    strategy = await db.get(Strategy, req.strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if not strategy.module_path or not strategy.class_name:
        raise HTTPException(
            status_code=422,
            detail="Strategy must have module_path and class_name (registry-based strategy required for optimization)",
        )

    if not req.param_grid:
        raise HTTPException(status_code=422, detail="param_grid must not be empty")

    total = 1
    for vals in req.param_grid.values():
        total *= len(vals)
    if total > 100000:
        raise HTTPException(
            status_code=422,
            detail=f"param_grid produces {total} combinations (max 100000). Reduce the sweep range.",
        )

    timeframe = req.timeframe or strategy.primary_tf or strategy.timeframe or "M15"

    opt = OptimizationRun(
        strategy_id=req.strategy_id,
        symbol=req.symbol,
        timeframe=timeframe,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_balance=req.initial_balance,
        spread_pips=req.spread_pips,
        execution_mode=req.execution_mode,
        volume=req.volume,
        risk_pct=req.risk_pct,
        commission_per_lot=req.commission_per_lot,
        tp_partial_close_ratio=req.tp_partial_close_ratio,
        max_workers=req.max_workers,
        csv_upload_id=req.csv_upload_id,
        csv_uploads=json.dumps(req.csv_uploads) if req.csv_uploads else None,
        param_grid=json.dumps(req.param_grid),
        optimize_metric=req.optimize_metric,
        status="pending",
        progress_pct=0,
        total_combinations=total,
        completed_combinations=0,
        created_at=datetime.now(UTC),
    )
    db.add(opt)
    await db.commit()
    await db.refresh(opt)

    from services.optimization_service import OptimizationService
    svc = OptimizationService()
    background_tasks.add_task(svc.run, opt.id)

    logger.info(
        "Optimization %d submitted | strategy=%s symbol=%s combos=%d metric=%s",
        opt.id, strategy.name, opt.symbol, total, req.optimize_metric,
    )
    return OptimizationRunOut.from_orm(opt)


@router.get("/optimize", response_model=list[OptimizationRunOut])
async def list_optimizations(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[OptimizationRunOut]:
    q = (
        select(OptimizationRun)
        .order_by(desc(OptimizationRun.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).scalars().all()
    return [OptimizationRunOut.from_orm(r) for r in rows]


@router.get("/optimize/{opt_id}", response_model=OptimizationRunOut)
async def get_optimization(opt_id: int, db: AsyncSession = Depends(get_db)) -> OptimizationRunOut:
    opt = await db.get(OptimizationRun, opt_id)
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    return OptimizationRunOut.from_orm(opt)


@router.post("/optimize/{opt_id}/cancel", response_model=OptimizationRunOut)
async def cancel_optimization(opt_id: int, db: AsyncSession = Depends(get_db)) -> OptimizationRunOut:
    """Request early stop of a running optimization. Sets status to 'cancelling'; the
    background worker will finish its current batch and save partial results."""
    opt = await db.get(OptimizationRun, opt_id)
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    if opt.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel optimization in status '{opt.status}'",
        )
    opt.status = "cancelling"
    await db.commit()
    await db.refresh(opt)
    logger.info("Optimization %d cancel requested", opt_id)
    return OptimizationRunOut.from_orm(opt)


@router.post("/optimize/{opt_id}/resume", response_model=OptimizationRunOut)
async def resume_optimization(
    opt_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> OptimizationRunOut:
    """Resume a cancelled optimization from where it left off.

    Loads existing partial results and skips already-completed combinations.
    Only allowed when status is 'cancelled'.
    """
    opt = await db.get(OptimizationRun, opt_id)
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    if opt.status != "cancelled":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot resume optimization in status '{opt.status}'",
        )
    opt.status = "running"
    await db.commit()
    await db.refresh(opt)
    from services.optimization_service import OptimizationService
    svc = OptimizationService()
    background_tasks.add_task(svc.run, opt.id, True)
    logger.info("Optimization %d resume requested", opt_id)
    return OptimizationRunOut.from_orm(opt)


_ALLOWED_SORT_METRICS = {
    "sharpe_ratio", "profit_factor", "total_return_pct", "win_rate",
    "expectancy", "max_drawdown_pct", "recovery_factor", "sortino_ratio",
    "total_trades", "avg_win", "avg_loss",
}
_LOWER_IS_BETTER = {"max_drawdown_pct"}


@router.get("/optimize/{opt_id}/results")
async def get_optimization_results(
    opt_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str = Query("sharpe_ratio"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return paginated, sortable optimization results.

    Response: {total, page, page_size, pages, results: [{params, metrics}, ...]}
    """
    if sort_by not in _ALLOWED_SORT_METRICS:
        raise HTTPException(400, f"sort_by must be one of: {sorted(_ALLOWED_SORT_METRICS)}")

    opt = await db.get(OptimizationRun, opt_id)
    if not opt:
        raise HTTPException(404, "Optimization run not found")

    all_results: list[dict] = json.loads(opt.results or "[]")
    total = len(all_results)

    # Sort
    reverse = order == "desc"
    lower_is_better = sort_by in _LOWER_IS_BETTER

    def _key(r: dict) -> float:
        v = r["metrics"].get(sort_by)
        if v is None:
            return float("inf") if (reverse != lower_is_better) else float("-inf")
        return float(v)

    all_results.sort(key=_key, reverse=reverse)

    # Paginate
    start = (page - 1) * page_size
    page_results = all_results[start: start + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "results": page_results,
    }
