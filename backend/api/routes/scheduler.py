"""Scheduler jobs — expose APScheduler job list via REST."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks
from db.postgres import AsyncSessionLocal
from services.position_maintenance import PositionMaintenanceService
from services.scheduler import get_scheduler

router = APIRouter()
logger = logging.getLogger(__name__)


def _describe_trigger(job) -> tuple[str, str]:
    """Return (trigger_type, human-readable description) for a job trigger."""
    trigger = job.trigger
    trigger_class = type(trigger).__name__

    if trigger_class == "CronTrigger":
        fields: dict[str, str] = {f.name: str(f) for f in trigger.fields if not f.is_default}
        # Map cron fields to a readable schedule
        minute = fields.get("minute", "*")
        hour = fields.get("hour", "*")
        dow = fields.get("day_of_week", "*")

        if dow not in ("*", "None"):
            return "cron", f"Weekly on {dow.upper()} at {hour}:{minute.zfill(2)} UTC"
        elif hour != "*" and minute == "0":
            hours_list = hour.split(",")
            if len(hours_list) == 1:
                return "cron", f"Daily at {hour.zfill(2)}:00"
            else:
                return "cron", f"Every {24 // len(hours_list)}h on the hour"
        elif hour == "*" and minute == "0":
            return "cron", "Every 1h on the hour (H1 candle)"
        elif minute not in ("*", "None"):
            mins = minute.split(",")
            if len(mins) == 4:
                return "cron", f"Every 15 min (M15 candle)"
            elif len(mins) == 2:
                return "cron", f"Every 30 min (M30 candle)"
            else:
                return "cron", f"At minutes: {minute}"
        return "cron", str(trigger)

    elif trigger_class == "IntervalTrigger":
        interval = trigger.interval
        total_seconds = int(interval.total_seconds())
        if total_seconds < 60:
            return "interval", f"Every {total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return "interval", f"Every {minutes} min"
        else:
            hours = total_seconds // 3600
            return "interval", f"Every {hours}h"

    elif trigger_class == "DateTrigger":
        return "date", "One-off (already ran or pending)"

    return "unknown", str(trigger)


def _advance_past_skips(
    trigger,
    start: datetime,
    skip_hours: list[int],
    skip_weekdays: list[int],
    tz: ZoneInfo,
    max_iterations: int = 200,
) -> datetime | None:
    """Walk forward through cron fire times until we find one not in skip_hours/skip_weekdays."""
    candidate = start
    for _ in range(max_iterations):
        local_dt = candidate.astimezone(tz)
        if local_dt.hour not in skip_hours and local_dt.weekday() not in skip_weekdays:
            return candidate
        next_candidate = trigger.get_next_fire_time(candidate, candidate + timedelta(seconds=1))
        if next_candidate is None:
            return None
        candidate = next_candidate
    return None


def _job_category(job_id: str) -> str:
    if job_id.startswith("strat_"):
        return "strategy"
    return "system"


def _job_name(job_id: str) -> str:
    known = {
        "position_maintenance_sweep": "Position Maintenance Sweep",
    }
    if job_id in known:
        return known[job_id]
    if job_id.startswith("strat_"):
        # strat_<binding_id>_<symbol>
        parts = job_id.split("_", 2)
        symbol = parts[2] if len(parts) >= 3 else "Unknown"
        binding_id = parts[1] if len(parts) >= 2 else "?"
        return f"Strategy Binding #{binding_id} — {symbol}"
    if job_id.startswith("manual_"):
        parts = job_id.split("_", 3)
        symbol = parts[2] if len(parts) >= 3 else "Unknown"
        return f"Manual Trigger — {symbol}"
    return job_id


@router.get("/jobs")
async def list_scheduler_jobs() -> list[dict[str, Any]]:
    """Return all currently registered APScheduler jobs with effective next_run_time."""
    from db.models import AccountStrategy
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    scheduler = get_scheduler()
    jobs = scheduler.get_jobs()

    # Pre-fetch skip configs for all bindings (skip_hours, skip_weekdays, timezone)
    skip_configs: dict[int, tuple[list[int], list[int], str]] = {}
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AccountStrategy).options(selectinload(AccountStrategy.strategy))
        )
        for binding in result.scalars().all():
            s = binding.strategy
            skip_h: list[int] = json.loads(s.skip_hours or "[]")
            skip_wd: list[int] = json.loads(s.skip_weekdays or "[]")
            skip_configs[binding.id] = (skip_h, skip_wd, s.skip_hours_timezone or "UTC")

    result_list = []
    for job in jobs:
        trigger_type, trigger_desc = _describe_trigger(job)
        next_run = job.next_run_time

        # For strategy jobs advance next_run past any skipped hours/weekdays
        effective_next_run = next_run
        if next_run and job.id.startswith("strat_"):
            parts = job.id.split("_", 2)
            try:
                binding_id = int(parts[1])
                config = skip_configs.get(binding_id)
                if config:
                    skip_h, skip_wd, tz_str = config
                    if skip_h or skip_wd:
                        try:
                            tz = ZoneInfo(tz_str)
                        except ZoneInfoNotFoundError:
                            tz = ZoneInfo("UTC")
                        effective_next_run = (
                            _advance_past_skips(job.trigger, next_run, skip_h, skip_wd, tz)
                            or next_run
                        )
            except (ValueError, IndexError):
                pass

        result_list.append(
            {
                "id": job.id,
                "name": _job_name(job.id),
                "trigger_type": trigger_type,
                "trigger_description": trigger_desc,
                "next_run_time": effective_next_run.isoformat() if effective_next_run else None,
                "category": _job_category(job.id),
            }
        )

    # Sort: strategy first, system last; then by next_run_time
    result_list.sort(
        key=lambda j: (
            0 if j["category"] == "strategy" else 1,
            j["next_run_time"] or "9999",
        )
    )
    return result_list


_maintenance_svc = PositionMaintenanceService()


async def _bg_maintenance_all() -> None:
    async with AsyncSessionLocal() as db:
        await _maintenance_svc.run_maintenance_sweep(db)


async def _bg_maintenance_for_account(account_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await _maintenance_svc.run_for_account(account_id, db)


@router.post("/run-maintenance", status_code=202)
async def run_maintenance_all(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Manually trigger a full maintenance sweep across all active accounts."""
    background_tasks.add_task(_bg_maintenance_all)
    return {"status": "accepted", "detail": "Maintenance sweep started for all accounts"}


@router.post("/run-maintenance/{account_id}", status_code=202)
async def run_maintenance_for_account(
    account_id: int,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Manually trigger a maintenance sweep for a single account."""
    background_tasks.add_task(_bg_maintenance_for_account, account_id)
    return {"status": "accepted", "detail": f"Maintenance sweep started for account {account_id}"}


async def _bg_maintenance_for_ticket(account_id: int, ticket: int) -> None:
    async with AsyncSessionLocal() as db:
        await _maintenance_svc.run_for_ticket(account_id, ticket, db)


@router.post("/run-maintenance/{account_id}/ticket/{ticket}", status_code=202)
async def run_maintenance_for_ticket(
    account_id: int,
    ticket: int,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Manually trigger maintenance for a single position by ticket."""
    background_tasks.add_task(_bg_maintenance_for_ticket, account_id, ticket)
    return {"status": "accepted", "detail": f"Maintenance started for ticket {ticket}"}
