"""Risk management rule toggles and thresholds."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class RiskSettingsResponse(BaseModel):
    drawdown_check_enabled: bool
    max_drawdown_pct: float
    position_limit_enabled: bool
    max_open_positions: int
    rate_limit_enabled: bool
    rate_limit_max_trades: int
    rate_limit_window_hours: float
    hedging_allowed: bool


class RiskSettingsPatch(BaseModel):
    drawdown_check_enabled: bool | None = None
    max_drawdown_pct: float | None = None
    position_limit_enabled: bool | None = None
    max_open_positions: int | None = None
    rate_limit_enabled: bool | None = None
    rate_limit_max_trades: int | None = None
    rate_limit_window_hours: float | None = None
    hedging_allowed: bool | None = None


def _risk_row_to_response(row) -> RiskSettingsResponse:
    return RiskSettingsResponse(
        drawdown_check_enabled=row.drawdown_check_enabled,
        max_drawdown_pct=row.max_drawdown_pct,
        position_limit_enabled=row.position_limit_enabled,
        max_open_positions=row.max_open_positions,
        rate_limit_enabled=row.rate_limit_enabled,
        rate_limit_max_trades=row.rate_limit_max_trades,
        rate_limit_window_hours=row.rate_limit_window_hours,
        hedging_allowed=row.hedging_allowed,
    )


@router.get("/risk", response_model=RiskSettingsResponse)
async def get_risk_settings(db: AsyncSession = Depends(get_db)) -> RiskSettingsResponse:
    """Return current risk rule toggles and thresholds."""
    from db.models import RiskSettings
    row = (await db.execute(select(RiskSettings).where(RiskSettings.id == 1))).scalar_one_or_none()
    if not row:
        # Should never happen after migration, but handle gracefully
        row = RiskSettings(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _risk_row_to_response(row)


@router.patch("/risk", response_model=RiskSettingsResponse)
async def patch_risk_settings(
    body: RiskSettingsPatch,
    db: AsyncSession = Depends(get_db),
) -> RiskSettingsResponse:
    """Update risk rule configuration (persisted to DB)."""
    from db.models import RiskSettings
    row = (await db.execute(select(RiskSettings).where(RiskSettings.id == 1))).scalar_one_or_none()
    if not row:
        row = RiskSettings(id=1)
        db.add(row)

    if body.drawdown_check_enabled is not None:
        row.drawdown_check_enabled = body.drawdown_check_enabled
    if body.max_drawdown_pct is not None:
        if not 0 < body.max_drawdown_pct <= 100:
            raise HTTPException(status_code=422, detail="max_drawdown_pct must be > 0 and <= 100")
        row.max_drawdown_pct = body.max_drawdown_pct
    if body.position_limit_enabled is not None:
        row.position_limit_enabled = body.position_limit_enabled
    if body.max_open_positions is not None:
        if body.max_open_positions < 1:
            raise HTTPException(status_code=422, detail="max_open_positions must be >= 1")
        row.max_open_positions = body.max_open_positions
    if body.rate_limit_enabled is not None:
        row.rate_limit_enabled = body.rate_limit_enabled
    if body.rate_limit_max_trades is not None:
        if body.rate_limit_max_trades < 1:
            raise HTTPException(status_code=422, detail="rate_limit_max_trades must be >= 1")
        row.rate_limit_max_trades = body.rate_limit_max_trades
    if body.rate_limit_window_hours is not None:
        if body.rate_limit_window_hours <= 0:
            raise HTTPException(status_code=422, detail="rate_limit_window_hours must be > 0")
        row.rate_limit_window_hours = body.rate_limit_window_hours
    if body.hedging_allowed is not None:
        row.hedging_allowed = body.hedging_allowed

    await db.commit()
    await db.refresh(row)
    logger.info("Risk settings updated | %s", body.model_dump(exclude_none=True))
    return _risk_row_to_response(row)


# ── Telegram Settings ──────────────────────────────────────────────────────────

