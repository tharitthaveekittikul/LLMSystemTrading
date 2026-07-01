"""Tests for the live news_enabled toggle hot-reloading APScheduler jobs.

Without services.scheduler.reschedule_news_jobs, PATCH /settings/global could
flip news_enabled in the DB/in-memory settings without the actual
news_fetch_daily / news_analyze_daily cron jobs being added or removed until
the next backend restart. These tests start/stop the shared scheduler
singleton locally so they don't interfere with other test modules.

AsyncIOScheduler.start() needs a running event loop, so both the fixture and
the tests are async (asyncio_mode = "auto" in pyproject.toml handles both).
"""
import pytest

from services.scheduler import reschedule_news_jobs
from services.scheduler._state import _scheduler

_JOB_IDS = ("news_fetch_daily", "news_analyze_daily")


@pytest.fixture
async def running_scheduler():
    was_running = _scheduler.running
    if not was_running:
        _scheduler.start(paused=True)  # paused: never actually fires jobs
    try:
        yield _scheduler
    finally:
        for job_id in _JOB_IDS:
            if _scheduler.get_job(job_id):
                _scheduler.remove_job(job_id)
        if not was_running and _scheduler.running:
            _scheduler.shutdown(wait=False)


async def test_reschedule_news_jobs_adds_jobs_when_enabled(running_scheduler):
    for job_id in _JOB_IDS:
        assert running_scheduler.get_job(job_id) is None

    reschedule_news_jobs(True)

    for job_id in _JOB_IDS:
        assert running_scheduler.get_job(job_id) is not None


async def test_reschedule_news_jobs_removes_jobs_when_disabled(running_scheduler):
    reschedule_news_jobs(True)
    for job_id in _JOB_IDS:
        assert running_scheduler.get_job(job_id) is not None

    reschedule_news_jobs(False)

    for job_id in _JOB_IDS:
        assert running_scheduler.get_job(job_id) is None


async def test_reschedule_news_jobs_is_noop_when_scheduler_not_running():
    assert not _scheduler.running
    reschedule_news_jobs(True)  # must not raise
    for job_id in _JOB_IDS:
        assert _scheduler.get_job(job_id) is None
