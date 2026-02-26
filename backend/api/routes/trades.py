from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import cast, Date, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Trade
from db.postgres import get_db

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
    query = select(Trade)
    if account_id:
        query = query.where(Trade.account_id == account_id)
    if open_only:
        query = query.where(Trade.closed_at == None)  # noqa: E711
    if date_from:
        query = query.where(cast(Trade.closed_at, Date) >= date_from)
    if date_to:
        query = query.where(cast(Trade.closed_at, Date) <= date_to)
    query = query.order_by(Trade.opened_at.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
