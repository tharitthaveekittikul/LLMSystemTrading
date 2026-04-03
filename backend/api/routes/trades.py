from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import cast, Date, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Account, Trade
from db.postgres import get_db

import logging
logger = logging.getLogger(__name__)

router = APIRouter()


class TradeResponse(BaseModel):
    id: int
    account_id: int
    ticket: int
    symbol: str
    direction: str
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    close_price: float | None
    profit: float | None
    opened_at: datetime
    closed_at: datetime | None
    source: str
    trade_analysis: str | None = None


@router.get("", response_model=list[TradeResponse])
async def list_trades(
    account_id: int | None = Query(None),
    open_only: bool = Query(False),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List trades with optional filters.

    date_from / date_to filter by closed_at date and apply only to closed trades.
    Open trades (closed_at IS NULL) are excluded when either date filter is active.
    Do not combine open_only=True with date filters — returns 400.
    """
    if open_only and (date_from or date_to):
        raise HTTPException(
            status_code=400,
            detail="Cannot combine open_only=true with date_from/date_to filters.",
        )

    if account_id is None:
        # All accounts: join to Account to convert USC profits → USD (÷ 100).
        query = select(Trade, Account.account_type).join(Account, Trade.account_id == Account.id)
        if open_only:
            query = query.where(Trade.closed_at == None)  # noqa: E711
        else:
            # Exclude cancelled/expired orders: closed_at set but no profit recorded
            query = query.where((Trade.closed_at == None) | (Trade.profit != None))  # noqa: E711
        if date_from:
            query = query.where(cast(Trade.closed_at, Date) >= date_from)
        if date_to:
            query = query.where(cast(Trade.closed_at, Date) <= date_to)
        query = query.order_by(Trade.opened_at.desc()).limit(limit)

        result = await db.execute(query)
        rows = result.all()

        out = []
        for trade, acct_type in rows:
            factor = 0.01 if acct_type == "USC" else 1.0
            out.append(TradeResponse(
                id=trade.id,
                account_id=trade.account_id,
                ticket=trade.ticket,
                symbol=trade.symbol,
                direction=trade.direction,
                volume=trade.volume,
                entry_price=trade.entry_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                close_price=trade.close_price,
                profit=round(trade.profit * factor, 2) if trade.profit is not None else None,
                opened_at=trade.opened_at,
                closed_at=trade.closed_at,
                source=trade.source,
                trade_analysis=trade.trade_analysis,
            ))
        return out
    else:
        # Single account: no conversion, native currency.
        query = select(Trade).where(Trade.account_id == account_id)
        if open_only:
            query = query.where(Trade.closed_at == None)  # noqa: E711
        else:
            # Exclude cancelled/expired orders: closed_at set but no profit recorded
            query = query.where((Trade.closed_at == None) | (Trade.profit != None))  # noqa: E711
        if date_from:
            query = query.where(cast(Trade.closed_at, Date) >= date_from)
        if date_to:
            query = query.where(cast(Trade.closed_at, Date) <= date_to)
        query = query.order_by(Trade.opened_at.desc()).limit(limit)

        result = await db.execute(query)
        return result.scalars().all()


class TradePatch(BaseModel):
    maintenance_enabled: bool | None = None


@router.patch("/{trade_id}", response_model=dict)
async def patch_trade(
    trade_id: int,
    body: TradePatch,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update trade properties (currently: maintenance_enabled toggle)."""
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if body.maintenance_enabled is not None:
        trade.maintenance_enabled = body.maintenance_enabled
    await db.commit()
    logger.info("Trade patched | id=%s maintenance_enabled=%s", trade_id, trade.maintenance_enabled)
    return {"id": trade_id, "maintenance_enabled": trade.maintenance_enabled}


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(trade_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch a single trade by ID."""
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@router.post("/{trade_id}/analyze", response_model=dict)
async def trigger_trade_analysis(trade_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Manually trigger post-trade LLM analysis for a closed trade.

    Clears any existing analysis first so it is always re-run.
    Returns immediately — analysis runs in the background.
    """
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.closed_at is None:
        raise HTTPException(status_code=400, detail="Trade is not closed yet")
    # Clear existing so _analyze doesn't skip it
    trade.trade_analysis = None
    await db.commit()

    import asyncio
    from services.trade_analyzer import analyze_closed_trade
    asyncio.ensure_future(analyze_closed_trade(trade_id))
    logger.info("Post-trade analysis triggered | trade_id=%s", trade_id)
    return {"trade_id": trade_id, "status": "queued"}
