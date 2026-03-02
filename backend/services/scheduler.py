from __future__ import annotations
import importlib
import json
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CANDLE_CRON: dict[str, dict] = {
    "M15": dict(minute="0,15,30,45"),
    "M30": dict(minute="0,30"),
    "H1":  dict(hour="*", minute="0"),
    "H4":  dict(hour="0,4,8,12,16,20", minute="0"),
    "D1":  dict(hour="0", minute="0"),
}

_scheduler = AsyncIOScheduler()


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler


def _job_id(binding_id: int, symbol: str) -> str:
    return f"strat_{binding_id}_{symbol}"


def _make_trigger(strategy):
    if strategy.trigger_type == "interval":
        return IntervalTrigger(minutes=strategy.interval_minutes or 15)
    return CronTrigger(**CANDLE_CRON.get(strategy.timeframe, CANDLE_CRON["M15"]))


def _build_overrides(strategy):
    """Return (symbols, StrategyOverrides, strategy_id) for this strategy."""
    from services.ai_trading import StrategyOverrides
    symbols = json.loads(strategy.symbols or "[]")
    if strategy.strategy_type == "code" and strategy.module_path and strategy.class_name:
        try:
            mod = importlib.import_module(strategy.module_path)
            instance = getattr(mod, strategy.class_name)()
            return (instance.symbols or symbols), StrategyOverrides(
                lot_size=instance.lot_size(),
                sl_pips=instance.sl_pips(),
                tp_pips=instance.tp_pips(),
                news_filter=instance.news_filter(),
                custom_prompt=instance.system_prompt(),
            ), strategy.id
        except Exception:
            logger.exception("Failed to load code strategy %s.%s — using DB config",
                             strategy.module_path, strategy.class_name)
    return symbols, StrategyOverrides(
        lot_size=strategy.lot_size,
        sl_pips=strategy.sl_pips,
        tp_pips=strategy.tp_pips,
        news_filter=strategy.news_filter,
        custom_prompt=strategy.custom_prompt,
    ), strategy.id


def _add_binding_jobs(scheduler: AsyncIOScheduler, binding) -> None:
    strategy = binding.strategy
    symbols, overrides, strategy_id = _build_overrides(strategy)
    trigger = _make_trigger(strategy)
    # Pass module_path/class_name so the job can reload the instance fresh each run.
    module_path = strategy.module_path if strategy.strategy_type == "code" else None
    class_name  = strategy.class_name  if strategy.strategy_type == "code" else None
    for symbol in symbols:
        job_id = _job_id(binding.id, symbol)
        scheduler.add_job(
            _run_strategy_job,
            trigger=trigger,
            id=job_id,
            args=[binding.account_id, symbol, strategy.timeframe, strategy_id, overrides,
                  module_path, class_name],
            replace_existing=True,
            misfire_grace_time=60,
        )
        logger.info("Scheduled %s (trigger=%s)", job_id, strategy.trigger_type)


async def _run_strategy_job(
    account_id: int, symbol: str, timeframe: str,
    strategy_id: int | None, overrides,
    module_path: str | None = None,
    class_name: str | None = None,
) -> None:
    from db.postgres import AsyncSessionLocal
    from services.ai_trading import AITradingService

    # Load code strategy instance fresh each run.
    strategy_instance = None
    if module_path and class_name:
        try:
            mod = importlib.import_module(module_path)
            strategy_instance = getattr(mod, class_name)()
        except Exception:
            logger.exception("Failed to load code strategy %s.%s — running LLM fallback",
                             module_path, class_name)

    try:
        async with AsyncSessionLocal() as db:
            service = AITradingService()
            result = await service.analyze_and_trade(
                account_id=account_id, symbol=symbol, timeframe=timeframe,
                db=db, strategy_id=strategy_id, strategy_overrides=overrides,
                strategy_instance=strategy_instance,
            )
            logger.info("Job done: account=%d symbol=%s action=%s order=%s",
                        account_id, symbol, result.signal.action, result.order_placed)
    except Exception as exc:
        logger.error(
            "Scheduled job failed | account=%d symbol=%s strategy_id=%s: %s",
            account_id, symbol, strategy_id, exc,
        )


async def start_scheduler(db: "AsyncSession") -> None:
    from db.models import AccountStrategy
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(AccountStrategy)
        .where(AccountStrategy.is_active.is_(True))
        .options(selectinload(AccountStrategy.strategy), selectinload(AccountStrategy.account))
    )
    bindings = [b for b in result.scalars().all()
                if b.account.is_active and b.strategy.is_active]
    for binding in bindings:
        _add_binding_jobs(_scheduler, binding)

    # Weekly HMM retrain — every Sunday 01:00 UTC
    from services.hmm_retrain import retrain_all_hmm_models
    _scheduler.add_job(
        retrain_all_hmm_models,
        trigger=CronTrigger(day_of_week="sun", hour=1, minute=0, timezone="UTC"),
        id="hmm_weekly_retrain",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("HMM weekly retrain job registered (Sunday 01:00 UTC)")

    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))


def add_binding_jobs(binding) -> None:
    """Call from API route when a binding is activated."""
    _add_binding_jobs(_scheduler, binding)


def remove_binding_jobs(binding_id: int, symbols: list[str]) -> None:
    """Call from API route when a binding is paused or deactivated."""
    for symbol in symbols:
        job_id = _job_id(binding_id, symbol)
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
            logger.info("Removed job %s", job_id)


def remove_all_binding_jobs(binding_id: int) -> None:
    """Remove all jobs for a binding by ID prefix (safe for code-type strategies)."""
    prefix = f"strat_{binding_id}_"
    for job in list(_scheduler.get_jobs()):
        if job.id.startswith(prefix):
            _scheduler.remove_job(job.id)
            logger.info("Removed job %s", job.id)


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
