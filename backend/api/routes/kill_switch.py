"""Kill switch HTTP routes — activate, deactivate, status, and log."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import KillSwitchLog
from db.postgres import get_db
from services import kill_switch

router = APIRouter()
logger = logging.getLogger(__name__)


class ActivateRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class KillSwitchLogResponse(BaseModel):
    id: int
    action: str
    reason: str | None
    triggered_by: str
    created_at: datetime


@router.get("")
async def get_status():
    """Return the current kill switch state."""
    return kill_switch.get_state()


@router.post("/activate")
async def activate(body: ActivateRequest):
    """Activate the kill switch — all order execution is immediately blocked."""
    logger.warning("Kill switch activate requested via API | reason=%s", body.reason)
    await kill_switch.activate(reason=body.reason, triggered_by="user")
    return kill_switch.get_state()


@router.post("/deactivate")
async def deactivate():
    """Deactivate the kill switch — order execution is re-enabled."""
    logger.warning("Kill switch deactivated via API")
    await kill_switch.deactivate(triggered_by="user")
    return kill_switch.get_state()


@router.get("/logs", response_model=list[KillSwitchLogResponse])
async def get_logs(db: AsyncSession = Depends(get_db)):
    """Return kill switch event history (most recent first)."""
    result = await db.execute(
        select(KillSwitchLog).order_by(desc(KillSwitchLog.created_at)).limit(100)
    )
    return result.scalars().all()
