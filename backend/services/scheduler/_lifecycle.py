"""Scheduler lifecycle: startup job registration, binding add/remove, manual trigger, shutdown."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from services.scheduler._group_job import _add_binding_jobs, _run_group_strategy_job
from services.scheduler._state import (
    _group_accounts,
    _group_bindings_by_strategy,
    _group_job_id,
    _make_trigger,
    _scheduler,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def start_scheduler(db: "AsyncSession") -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from db.models import AccountStrategy
    result = await db.execute(
        select(AccountStrategy)
        .where(AccountStrategy.is_active.is_(True))
        .options(selectinload(AccountStrategy.strategy), selectinload(AccountStrategy.account))
    )
    bindings = [b for b in result.scalars().all()
                if b.account.is_active and b.strategy.is_active]

    # Group bindings by (strategy_id, symbol) and register one job per group
    groups = _group_bindings_by_strategy(bindings)
    for (strategy_id, symbol), group_data in groups.items():
        strategy = group_data["strategy"]
        job_id = _group_job_id(strategy_id, symbol)
        _group_accounts[job_id] = group_data["account_entries"]
        trigger = _make_trigger(strategy)
        _scheduler.add_job(
            _run_group_strategy_job,
            trigger=trigger,
            id=job_id,
            args=[strategy_id, symbol, strategy.timeframe,
                  group_data["module_path"], group_data["class_name"]],
            replace_existing=True,
            misfire_grace_time=60,
        )
        account_ids = [a for a, _ in group_data["account_entries"]]
        logger.info("Group job registered %s | accounts=%s", job_id, account_ids)

    # Position maintenance sweep — runs every maintenance_interval_minutes
    from core.config import settings
    from db.postgres import AsyncSessionLocal
    from services.position_maintenance import PositionMaintenanceService
    _maintenance_service = PositionMaintenanceService()

    async def _run_maintenance_sweep() -> None:
        async with AsyncSessionLocal() as db:
            await _maintenance_service.run_maintenance_sweep(db)

    _scheduler.add_job(
        _run_maintenance_sweep,
        trigger=IntervalTrigger(minutes=settings.maintenance_interval_minutes),
        id="position_maintenance_sweep",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info(
        "Position maintenance job registered | interval=%dmin enabled=%s",
        settings.maintenance_interval_minutes,
        settings.maintenance_task_enabled,
    )

    # News calendar jobs — only when news_enabled
    if settings.news_enabled:
        _register_news_jobs()
        logger.info("News calendar jobs registered (fetch 23:00 UTC, analyze 00:00 UTC)")
    else:
        logger.info("News calendar jobs skipped (news_enabled=False)")

    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))


# ── News calendar jobs (fetch 23:00 UTC, analyze 00:00 UTC) ─────────────────

async def _run_news_fetch_job() -> None:
    from db.postgres import AsyncSessionLocal
    async with AsyncSessionLocal() as _db:
        from services.news_fetcher import fetch_and_store_events
        try:
            count = await fetch_and_store_events(_db)
            logger.info("Scheduled news fetch complete | rows=%d", count)
        except Exception as exc:
            logger.error("Scheduled news fetch failed: %s", exc)


async def _run_news_analyze_job() -> None:
    from db.postgres import AsyncSessionLocal
    async with AsyncSessionLocal() as _db:
        from services.news_analyzer import analyze_today_events
        try:
            count = await analyze_today_events(_db)
            logger.info("Scheduled news analysis complete | analyzed=%d", count)
        except Exception as exc:
            logger.error("Scheduled news analysis failed: %s", exc)


def _register_news_jobs() -> None:
    """Add the news fetch/analyze cron jobs if they aren't already registered."""
    # Fetch at 23:00 UTC = 06:00 Bangkok
    _scheduler.add_job(
        _run_news_fetch_job,
        trigger=CronTrigger(hour=23, minute=0, timezone="UTC"),
        id="news_fetch_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Analyze at 00:00 UTC = 07:00 Bangkok
    _scheduler.add_job(
        _run_news_analyze_job,
        trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="news_analyze_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )


def reschedule_news_jobs(enabled: bool) -> None:
    """Add or remove the news calendar jobs after a live `news_enabled` toggle.

    Without this, the PATCH /settings/global endpoint only flips the
    in-memory/DB flag — the APScheduler jobs registered at `start_scheduler()`
    time would keep running (or keep NOT running) until the next backend
    restart. Called from the settings PATCH route so the toggle takes effect
    immediately, matching the maintenance-interval hot-reload pattern.
    """
    if not _scheduler.running:
        return
    if enabled:
        if _scheduler.get_job("news_fetch_daily") is None or _scheduler.get_job("news_analyze_daily") is None:
            _register_news_jobs()
            logger.info("News calendar jobs registered live (news_enabled toggled on)")
    else:
        removed = False
        for job_id in ("news_fetch_daily", "news_analyze_daily"):
            if _scheduler.get_job(job_id):
                _scheduler.remove_job(job_id)
                removed = True
        if removed:
            logger.info("News calendar jobs removed live (news_enabled toggled off)")


def add_binding_jobs(binding) -> None:
    """Call from API route when a binding is activated."""
    _add_binding_jobs(_scheduler, binding)


def remove_binding_jobs(_binding_id: int, account_id: int, strategy_id: int, symbols: list[str]) -> None:
    """Remove an account from all group jobs for a binding.

    If removing the account leaves the group empty, the APScheduler job is removed too.

    NOTE: Callers must pass account_id and strategy_id (new params — update call sites).
    """
    for symbol in symbols:
        job_id = _group_job_id(strategy_id, symbol)
        existing = _group_accounts.get(job_id, [])
        updated = [(acc_id, ov) for acc_id, ov in existing if acc_id != account_id]
        if updated:
            _group_accounts[job_id] = updated
            logger.info("Removed account %d from group %s | remaining=%s",
                        account_id, job_id, [a for a, _ in updated])
        else:
            _group_accounts.pop(job_id, None)
            if _scheduler.get_job(job_id):
                _scheduler.remove_job(job_id)
                logger.info("Group job %s removed (no accounts remaining)", job_id)


def remove_all_binding_jobs(_binding_id: int, account_id: int, strategy_id: int) -> None:
    """Remove an account from all group jobs for a strategy (all symbols).

    NOTE: Callers must pass account_id and strategy_id (new params — update call sites).
    """
    prefix = f"strat_{strategy_id}_"
    for job_id in list(_group_accounts.keys()):
        if not job_id.startswith(prefix):
            continue
        existing = _group_accounts[job_id]
        updated = [(acc_id, ov) for acc_id, ov in existing if acc_id != account_id]
        if updated:
            _group_accounts[job_id] = updated
        else:
            _group_accounts.pop(job_id, None)
            if _scheduler.get_job(job_id):
                _scheduler.remove_job(job_id)
                logger.info("Group job %s removed (no accounts remaining)", job_id)


def reschedule_maintenance_job(interval_minutes: int) -> None:
    """Update the maintenance sweep trigger after a settings change."""
    if not _scheduler.running:
        return
    _maintenance_service_ref = None
    existing = _scheduler.get_job("position_maintenance_sweep")
    if existing:
        _maintenance_service_ref = existing.func
    # Build a fresh closure that re-creates its own db session
    from db.postgres import AsyncSessionLocal

    async def _run_maintenance_sweep() -> None:
        from services.position_maintenance import PositionMaintenanceService
        async with AsyncSessionLocal() as db:
            await PositionMaintenanceService().run_maintenance_sweep(db)

    _scheduler.add_job(
        _run_maintenance_sweep if _maintenance_service_ref is None else _maintenance_service_ref,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="position_maintenance_sweep",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Maintenance job rescheduled | interval=%dmin", interval_minutes)


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def trigger_binding_manually(binding) -> None:
    """Manually trigger a group job once, immediately."""
    from datetime import timezone
    strategy = binding.strategy
    symbols = json.loads(strategy.symbols or "[]")
    module_path = strategy.module_path if strategy.execution_mode != "llm_only" else None
    class_name = strategy.class_name if strategy.execution_mode != "llm_only" else None

    for symbol in symbols:
        one_off_id = f"manual_{strategy.id}_{symbol}_{int(datetime.now(timezone.utc).timestamp())}"
        try:
            _scheduler.add_job(
                _run_group_strategy_job,
                trigger="date",
                run_date=datetime.now(timezone.utc),
                id=one_off_id,
                args=[strategy.id, symbol, strategy.timeframe, module_path, class_name, True],
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info("Manually triggered group job %s (skip-hours bypassed)", one_off_id)
        except Exception as e:
            logger.exception("Failed to trigger group job manually %s: %s", one_off_id, e)
