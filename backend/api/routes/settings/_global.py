"""Global app settings (maintenance interval, news toggle, agent-pipeline toggles)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.models import GlobalSettings as GlobalSettingsModel
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class GlobalSettings(BaseModel):
    maintenance_interval_minutes: int
    maintenance_task_enabled: bool
    llm_confidence_threshold: float
    news_enabled: bool
    enable_agent_pipeline: bool
    enable_indicator_agent: bool
    enable_pattern_agent: bool
    enable_trend_agent: bool


class GlobalSettingsPatch(BaseModel):
    maintenance_interval_minutes: int | None = None
    maintenance_task_enabled: bool | None = None
    llm_confidence_threshold: float | None = None
    news_enabled: bool | None = None
    enable_agent_pipeline: bool | None = None
    enable_indicator_agent: bool | None = None
    enable_pattern_agent: bool | None = None
    enable_trend_agent: bool | None = None


@router.get("/global", response_model=GlobalSettings)
async def get_global_settings(db: AsyncSession = Depends(get_db)) -> GlobalSettings:
    """Return current global settings, preferring DB-persisted values."""
    row = (await db.execute(
        select(GlobalSettingsModel).where(GlobalSettingsModel.id == 1)
    )).scalar_one_or_none()
    if row:
        return GlobalSettings(
            maintenance_interval_minutes=row.maintenance_interval_minutes,
            maintenance_task_enabled=row.maintenance_task_enabled,
            llm_confidence_threshold=row.llm_confidence_threshold,
            news_enabled=row.news_enabled,
            enable_agent_pipeline=row.enable_agent_pipeline,
            enable_indicator_agent=row.enable_indicator_agent,
            enable_pattern_agent=row.enable_pattern_agent,
            enable_trend_agent=row.enable_trend_agent,
        )
    # Fallback to in-memory config (first boot before migration runs)
    return GlobalSettings(
        maintenance_interval_minutes=settings.maintenance_interval_minutes,
        maintenance_task_enabled=settings.maintenance_task_enabled,
        llm_confidence_threshold=settings.llm_confidence_threshold,
        news_enabled=settings.news_enabled,
        enable_agent_pipeline=settings.enable_agent_pipeline,
        enable_indicator_agent=settings.enable_indicator_agent,
        enable_pattern_agent=settings.enable_pattern_agent,
        enable_trend_agent=settings.enable_trend_agent,
    )


@router.patch("/global", response_model=GlobalSettings)
async def patch_global_settings(
    body: GlobalSettingsPatch,
    db: AsyncSession = Depends(get_db),
) -> GlobalSettings:
    """Update global settings — persisted to DB and applied in-memory immediately."""
    row = (await db.execute(
        select(GlobalSettingsModel).where(GlobalSettingsModel.id == 1)
    )).scalar_one_or_none()
    if not row:
        row = GlobalSettingsModel(id=1)
        db.add(row)

    if body.maintenance_interval_minutes is not None:
        if body.maintenance_interval_minutes < 1:
            raise HTTPException(status_code=422, detail="maintenance_interval_minutes must be >= 1")
        row.maintenance_interval_minutes = body.maintenance_interval_minutes
        settings.maintenance_interval_minutes = body.maintenance_interval_minutes
        from services.scheduler import reschedule_maintenance_job
        reschedule_maintenance_job(body.maintenance_interval_minutes)
    if body.maintenance_task_enabled is not None:
        row.maintenance_task_enabled = body.maintenance_task_enabled
        settings.maintenance_task_enabled = body.maintenance_task_enabled
    if body.llm_confidence_threshold is not None:
        if not 0.0 <= body.llm_confidence_threshold <= 1.0:
            raise HTTPException(status_code=422, detail="llm_confidence_threshold must be 0.0-1.0")
        row.llm_confidence_threshold = body.llm_confidence_threshold
        settings.llm_confidence_threshold = body.llm_confidence_threshold
    if body.news_enabled is not None:
        row.news_enabled = body.news_enabled
        settings.news_enabled = body.news_enabled
    if body.enable_agent_pipeline is not None:
        row.enable_agent_pipeline = body.enable_agent_pipeline
        settings.enable_agent_pipeline = body.enable_agent_pipeline
    if body.enable_indicator_agent is not None:
        row.enable_indicator_agent = body.enable_indicator_agent
        settings.enable_indicator_agent = body.enable_indicator_agent
    if body.enable_pattern_agent is not None:
        row.enable_pattern_agent = body.enable_pattern_agent
        settings.enable_pattern_agent = body.enable_pattern_agent
    if body.enable_trend_agent is not None:
        row.enable_trend_agent = body.enable_trend_agent
        settings.enable_trend_agent = body.enable_trend_agent

    await db.commit()
    await db.refresh(row)
    logger.info("Global settings persisted to DB | %s", body.model_dump(exclude_none=True))
    return await get_global_settings(db)


# ── Risk Settings ──────────────────────────────────────────────────────────

