"""Scheduler singleton, group-job account registry, and small trigger/grouping helpers."""
from __future__ import annotations

import importlib
import json
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


CANDLE_CRON: dict[str, dict] = {
    "M15": dict(minute="0,15,30,45"),
    "M30": dict(minute="0,30"),
    "H1":  dict(hour="*", minute="0"),
    "H4":  dict(hour="0,4,8,12,16,20", minute="0"),
    "D1":  dict(hour="0", minute="0"),
}

_scheduler = AsyncIOScheduler()

# Maps group job_id → list of (account_id, overrides_dict) for runtime add/remove
_group_accounts: dict[str, list[tuple[int, dict]]] = {}


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler


def _make_trigger(strategy):
    if strategy.trigger_type == "interval":
        return IntervalTrigger(minutes=strategy.interval_minutes or 15)
    return CronTrigger(**CANDLE_CRON.get(strategy.timeframe, CANDLE_CRON["M15"]))


def _build_overrides(strategy):
    """Return (symbols, StrategyOverrides, strategy_id) for this strategy."""
    from services.ai_trading import StrategyOverrides
    symbols = json.loads(strategy.symbols or "[]")
    if strategy.execution_mode != "llm_only" and strategy.module_path and strategy.class_name:
        try:
            mod = importlib.import_module(strategy.module_path)
            instance = getattr(mod, strategy.class_name)()
            if hasattr(instance, "apply_db_config"):
                instance.apply_db_config(strategy)

            # AbstractStrategy subclasses expose .symbols as a list attribute directly
            if hasattr(instance, "primary_tf"):
                instance_symbols = getattr(instance, "symbols", None) or symbols
                return instance_symbols, StrategyOverrides(), strategy.id
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


def _group_job_id(strategy_id: int, symbol: str) -> str:
    return f"strat_{strategy_id}_{symbol}"


def _group_bindings_by_strategy(
    bindings: list,
) -> dict[tuple[int, str], dict]:
    """Group active bindings by (strategy_id, symbol).

    Returns dict keyed by (strategy_id, symbol) with structure:
      {"strategy": ..., "account_entries": [(account_id, overrides_dict), ...],
       "module_path": str | None, "class_name": str | None}
    """
    groups: dict[tuple[int, str], dict] = {}
    for binding in bindings:
        strategy = binding.strategy
        symbols = json.loads(strategy.symbols or "[]")
        _, overrides, _ = _build_overrides(strategy)
        module_path = strategy.module_path if strategy.execution_mode != "llm_only" else None
        class_name = strategy.class_name if strategy.execution_mode != "llm_only" else None

        for symbol in symbols:
            key = (strategy.id, symbol)
            if key not in groups:
                groups[key] = {
                    "strategy": strategy,
                    "account_entries": [],
                    "module_path": module_path,
                    "class_name": class_name,
                }
            groups[key]["account_entries"].append(
                (binding.account_id, overrides.model_dump())
            )
    return groups


