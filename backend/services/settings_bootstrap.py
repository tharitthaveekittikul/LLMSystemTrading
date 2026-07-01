"""One-time startup helper: ensure the GlobalSettings singleton row exists.

Called once from main.py's lifespan, before any route can read/patch
`/settings/global`. Extracted into its own module so the "never overwrite an
explicitly-set row" rule is independently testable without booting the full
FastAPI app.

Detection rule (see docs/pipeline-upgrade-plans/02-news-enable-and-calendar-page.md):
the row not existing at all is the only signal that means "never explicitly
set". If the row exists — with news_enabled True *or* False — it is left
completely untouched, since an operator may have deliberately chosen either
value.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.models import GlobalSettings as GlobalSettingsModel

logger = logging.getLogger(__name__)


async def ensure_global_settings_row(db: AsyncSession) -> GlobalSettingsModel:
    """Return the existing GlobalSettings row (id=1), creating it if absent.

    A freshly-created row is seeded from the current in-memory `settings`
    (i.e. config.py defaults, overridable via .env) — this is what makes the
    `news_enabled` default-flip take effect for a fresh deploy. An existing
    row is returned as-is and never mutated here.
    """
    row = (await db.execute(
        select(GlobalSettingsModel).where(GlobalSettingsModel.id == 1)
    )).scalar_one_or_none()
    if row is not None:
        return row

    row = GlobalSettingsModel(
        id=1,
        maintenance_interval_minutes=settings.maintenance_interval_minutes,
        maintenance_task_enabled=settings.maintenance_task_enabled,
        llm_confidence_threshold=settings.llm_confidence_threshold,
        news_enabled=settings.news_enabled,
        enable_agent_pipeline=settings.enable_agent_pipeline,
        enable_indicator_agent=settings.enable_indicator_agent,
        enable_pattern_agent=settings.enable_pattern_agent,
        enable_trend_agent=settings.enable_trend_agent,
    )
    db.add(row)
    await db.commit()
    logger.info(
        "GlobalSettings row created on first boot | news_enabled=%s (from config default/.env)",
        row.news_enabled,
    )
    return row
