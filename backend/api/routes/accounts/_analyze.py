"""On-demand LLM market analysis for a single account/symbol."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.accounts._schemas import AnalyzeRequest, AnalyzeResponse
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{account_id}/analyze", response_model=AnalyzeResponse)
async def analyze_account(
    account_id: int,
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run LLM market analysis and conditionally execute a trade.

    Returns the signal plus whether an order was placed.
    Errors: 404 account not found, 429 rate limited, 502/503 MT5 unavailable.
    """
    from services.ai_trading import AITradingService

    service = AITradingService()
    result = await service.analyze_and_trade(
        account_id=account_id,
        symbol=body.symbol,
        timeframe=body.timeframe,
        db=db,
    )
    return AnalyzeResponse(
        action=result.signal.action,
        entry=result.signal.entry,
        stop_loss=result.signal.stop_loss,
        take_profit=result.signal.take_profit,
        confidence=result.signal.confidence,
        rationale=result.signal.rationale,
        timeframe=result.signal.timeframe,
        order_placed=result.order_placed,
        ticket=result.ticket,
        journal_id=result.journal_id,
    )
