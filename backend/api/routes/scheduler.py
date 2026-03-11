"""Scheduler jobs — expose APScheduler job list via REST."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

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


def _job_category(job_id: str) -> str:
    if job_id.startswith("strat_"):
        return "strategy"
    return "system"


def _job_name(job_id: str) -> str:
    known = {
        "hmm_weekly_retrain": "HMM Model Weekly Retrain",
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
    """Return all currently registered APScheduler jobs."""
    scheduler = get_scheduler()
    jobs = scheduler.get_jobs()

    result = []
    for job in jobs:
        trigger_type, trigger_desc = _describe_trigger(job)
        next_run = job.next_run_time
        result.append(
            {
                "id": job.id,
                "name": _job_name(job.id),
                "trigger_type": trigger_type,
                "trigger_description": trigger_desc,
                "next_run_time": next_run.isoformat() if next_run else None,
                "category": _job_category(job.id),
            }
        )

    # Sort: strategy first, system last; then by next_run_time
    result.sort(
        key=lambda j: (
            0 if j["category"] == "strategy" else 1,
            j["next_run_time"] or "9999",
        )
    )
    return result
