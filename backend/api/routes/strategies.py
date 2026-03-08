from __future__ import annotations
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Account, AccountStrategy, AIJournal, BacktestRun, Strategy, Trade
from db.postgres import get_db
from services.scheduler import add_binding_jobs, remove_binding_jobs, remove_all_binding_jobs

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class StrategyCreate(BaseModel):
    name: str
    description: str | None = None
    strategy_type: str = "config"
    execution_mode: str = "llm_only"
    trigger_type: str = "candle_close"
    interval_minutes: int | None = None
    symbols: list[str] = []
    timeframe: str = "M15"
    primary_tf: str = "M15"
    context_tfs: list[str] = []
    lot_size: float | None = None
    sl_pips: float | None = None
    tp_pips: float | None = None
    news_filter: bool = True
    custom_prompt: str | None = None
    module_path: str | None = None
    class_name: str | None = None


class StrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    strategy_type: str | None = None
    execution_mode: str | None = None
    trigger_type: str | None = None
    interval_minutes: int | None = None
    symbols: list[str] | None = None
    timeframe: str | None = None
    primary_tf: str | None = None
    context_tfs: list[str] | None = None
    lot_size: float | None = None
    sl_pips: float | None = None
    tp_pips: float | None = None
    news_filter: bool | None = None
    custom_prompt: str | None = None
    module_path: str | None = None
    class_name: str | None = None
    is_active: bool | None = None


class StrategyResponse(BaseModel):
    id: int
    name: str
    description: str | None
    strategy_type: str
    execution_mode: str
    trigger_type: str
    interval_minutes: int | None
    symbols: list[str]
    timeframe: str
    primary_tf: str
    context_tfs: list[str]
    lot_size: float | None
    sl_pips: float | None
    tp_pips: float | None
    news_filter: bool
    custom_prompt: str | None
    module_path: str | None
    class_name: str | None
    is_active: bool
    binding_count: int = 0
    model_config = {"from_attributes": True}


class BindRequest(BaseModel):
    account_id: int
    is_active: bool = True


class BindingResponse(BaseModel):
    id: int
    account_id: int
    strategy_id: int
    is_active: bool
    account_name: str
    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_response(strategy: Strategy, binding_count: int = 0) -> StrategyResponse:
    return StrategyResponse(
        id=strategy.id,
        name=strategy.name,
        description=strategy.description,
        strategy_type=strategy.strategy_type,
        execution_mode=strategy.execution_mode,
        trigger_type=strategy.trigger_type,
        interval_minutes=strategy.interval_minutes,
        symbols=json.loads(strategy.symbols or "[]"),
        timeframe=strategy.timeframe,
        primary_tf=strategy.primary_tf,
        context_tfs=json.loads(strategy.context_tfs or "[]"),
        lot_size=strategy.lot_size,
        sl_pips=strategy.sl_pips,
        tp_pips=strategy.tp_pips,
        news_filter=strategy.news_filter,
        custom_prompt=strategy.custom_prompt,
        module_path=strategy.module_path,
        class_name=strategy.class_name,
        is_active=strategy.is_active,
        binding_count=binding_count,
    )


async def _get_or_404(db: AsyncSession, strategy_id: int) -> Strategy:
    row = await db.get(Strategy, strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return row


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[StrategyResponse])
async def list_strategies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Strategy).options(selectinload(Strategy.account_bindings))
    )
    rows = result.scalars().all()
    return [_to_response(s, len(s.account_bindings)) for s in rows]


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(body: StrategyCreate, db: AsyncSession = Depends(get_db)):
    # Derive strategy_type from execution_mode when not explicitly overriding
    execution_mode = body.execution_mode or "llm_only"
    strategy_type = body.strategy_type
    if execution_mode == "llm_only":
        strategy_type = "prompt"
    elif execution_mode in {"rule_only", "rule_then_llm", "hybrid_validator", "multi_agent"}:
        strategy_type = "code"
    strategy = Strategy(
        name=body.name,
        description=body.description,
        strategy_type=strategy_type,
        execution_mode=execution_mode,
        trigger_type=body.trigger_type,
        interval_minutes=body.interval_minutes,
        symbols=json.dumps(body.symbols),
        timeframe=body.timeframe,
        primary_tf=body.primary_tf,
        context_tfs=json.dumps(body.context_tfs),
        lot_size=body.lot_size,
        sl_pips=body.sl_pips,
        tp_pips=body.tp_pips,
        news_filter=body.news_filter,
        custom_prompt=body.custom_prompt,
        module_path=body.module_path,
        class_name=body.class_name,
    )
    db.add(strategy)
    try:
        await db.commit()
        await db.refresh(strategy)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Strategy name already exists")
    logger.info("Strategy created | id=%s name=%s", strategy.id, strategy.name)
    return _to_response(strategy)


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Strategy)
        .where(Strategy.id == strategy_id)
        .options(selectinload(Strategy.account_bindings))
    )
    strategy = result.scalar_one_or_none()
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _to_response(strategy, len(strategy.account_bindings))


@router.patch("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int, body: StrategyUpdate, db: AsyncSession = Depends(get_db)
):
    strategy = await _get_or_404(db, strategy_id)
    data = body.model_dump(exclude_none=True)
    # strategy_type is always derived from execution_mode; never set it directly
    data.pop("strategy_type", None)
    if "symbols" in data:
        data["symbols"] = json.dumps(data["symbols"])
    if "context_tfs" in data:
        data["context_tfs"] = json.dumps(data["context_tfs"])
    for key, value in data.items():
        setattr(strategy, key, value)
    if body.execution_mode is not None:
        # Keep strategy_type in sync with execution_mode
        if body.execution_mode == "llm_only":
            strategy.strategy_type = "prompt"
        elif body.execution_mode in {"rule_only", "rule_then_llm", "hybrid_validator", "multi_agent"}:
            strategy.strategy_type = "code"
    try:
        await db.commit()
        await db.refresh(strategy)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Strategy name already exists")
    logger.info("Strategy updated | id=%s", strategy_id)
    # Reschedule active bindings so they immediately use the updated config
    if strategy.is_active:
        bindings_result = await db.execute(
            select(AccountStrategy)
            .where(AccountStrategy.strategy_id == strategy_id, AccountStrategy.is_active.is_(True))
            .options(selectinload(AccountStrategy.account))
        )
        for binding in bindings_result.scalars().all():
            if binding.account.is_active:
                remove_all_binding_jobs(binding.id)
                binding.strategy = strategy
                add_binding_jobs(binding)
    return _to_response(strategy)


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    strategy = await _get_or_404(db, strategy_id)
    # Remove all scheduler jobs for this strategy's bindings
    result = await db.execute(
        select(AccountStrategy).where(AccountStrategy.strategy_id == strategy_id)
    )
    bindings = result.scalars().all()
    for binding in bindings:
        remove_all_binding_jobs(binding.id)
    await db.delete(strategy)
    await db.commit()
    logger.info("Strategy deleted | id=%s", strategy_id)


@router.post(
    "/{strategy_id}/bind",
    response_model=BindingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bind_account(
    strategy_id: int, body: BindRequest, db: AsyncSession = Depends(get_db)
):
    strategy = await _get_or_404(db, strategy_id)
    account = await db.get(Account, body.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    binding = AccountStrategy(
        account_id=body.account_id,
        strategy_id=strategy_id,
        is_active=body.is_active,
    )
    db.add(binding)
    try:
        await db.commit()
        await db.refresh(binding)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Account already bound to this strategy")
    if binding.is_active and account.is_active and strategy.is_active:
        binding.strategy = strategy
        binding.account = account
        add_binding_jobs(binding)
    logger.info(
        "Binding created | id=%s account_id=%s strategy_id=%s is_active=%s",
        binding.id, binding.account_id, binding.strategy_id, binding.is_active,
    )
    return BindingResponse(
        id=binding.id,
        account_id=binding.account_id,
        strategy_id=binding.strategy_id,
        is_active=binding.is_active,
        account_name=account.name,
    )


@router.patch("/{strategy_id}/bind/{account_id}", response_model=BindingResponse)
async def toggle_binding(
    strategy_id: int,
    account_id: int,
    body: BindRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AccountStrategy)
        .where(
            AccountStrategy.strategy_id == strategy_id,
            AccountStrategy.account_id == account_id,
        )
        .options(
            selectinload(AccountStrategy.strategy),
            selectinload(AccountStrategy.account),
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    old_active = binding.is_active
    binding.is_active = body.is_active
    await db.commit()
    await db.refresh(binding)
    symbols = json.loads(binding.strategy.symbols or "[]")
    if not old_active and body.is_active:
        if binding.account.is_active and binding.strategy.is_active:
            add_binding_jobs(binding)
    elif old_active and not body.is_active:
        remove_binding_jobs(binding.id, symbols)
    logger.info(
        "Binding toggled | id=%s account_id=%s strategy_id=%s is_active=%s",
        binding.id, account_id, strategy_id, binding.is_active,
    )
    return BindingResponse(
        id=binding.id,
        account_id=binding.account_id,
        strategy_id=binding.strategy_id,
        is_active=binding.is_active,
        account_name=binding.account.name,
    )


@router.delete(
    "/{strategy_id}/bind/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_account(
    strategy_id: int, account_id: int, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(AccountStrategy)
        .where(
            AccountStrategy.strategy_id == strategy_id,
            AccountStrategy.account_id == account_id,
        )
        .options(selectinload(AccountStrategy.strategy))
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    symbols = json.loads(binding.strategy.symbols or "[]")
    remove_binding_jobs(binding.id, symbols)
    await db.delete(binding)
    await db.commit()
    logger.info(
        "Binding removed | account_id=%s strategy_id=%s", account_id, strategy_id
    )


@router.get("/{strategy_id}/bindings", response_model=list[BindingResponse])
async def list_bindings(strategy_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, strategy_id)
    result = await db.execute(
        select(AccountStrategy)
        .where(AccountStrategy.strategy_id == strategy_id)
        .options(selectinload(AccountStrategy.account))
    )
    bindings = result.scalars().all()
    return [
        BindingResponse(
            id=b.id,
            account_id=b.account_id,
            strategy_id=b.strategy_id,
            is_active=b.is_active,
            account_name=b.account.name,
        )
        for b in bindings
    ]


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
