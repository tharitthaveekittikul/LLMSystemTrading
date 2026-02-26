from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
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
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = select(Trade)
    if account_id:
        query = query.where(Trade.account_id == account_id)
    if open_only:
        query = query.where(Trade.closed_at == None)  # noqa: E711
    query = query.order_by(Trade.opened_at.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
