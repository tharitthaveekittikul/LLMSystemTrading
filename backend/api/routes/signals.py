"""AI Signals — read-only endpoint over the ai_journal table."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AIJournal
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class SignalResponse(BaseModel):
    id: int
    account_id: int
    symbol: str
    timeframe: str
    signal: str
    confidence: float
    rationale: str
    llm_provider: str
    model_name: str
    created_at: datetime
    trade_id: int | None


@router.get("", response_model=list[SignalResponse])
async def list_signals(
    account_id: int | None = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List AI journal entries (most recent first)."""
    query = select(AIJournal).order_by(desc(AIJournal.created_at)).limit(limit)
    if account_id is not None:
        query = query.where(AIJournal.account_id == account_id)
    result = await db.execute(query)
    return result.scalars().all()
