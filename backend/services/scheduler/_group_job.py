"""The group strategy job: compute one signal per (strategy, symbol) and fan it out to accounts."""
from __future__ import annotations

import importlib
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.postgres import AsyncSessionLocal
from services.ai_trading import AITradingService
from services.scheduler._risk import _get_primary_account, _preflight_risk_check
from services.scheduler._state import (
    _build_overrides,
    _group_accounts,
    _group_job_id,
    _make_trigger,
)

logger = logging.getLogger(__name__)


async def _run_group_strategy_job(
    strategy_id: int | None,
    symbol: str,
    timeframe: str,
    module_path: str | None = None,
    class_name: str | None = None,
    bypass_skip_hours: bool = False,
) -> None:
    """Group job: compute signal once, execute per account.

    Reads account list from _group_accounts[job_id]. If the list is empty or the job
    has been removed, exits immediately.

    bypass_skip_hours: when True (manual trigger), the skip-hour/skip-weekday guard
    is not evaluated — a manual click always runs, regardless of configured quiet hours.
    """
    from services.ai_trading import StrategyOverrides

    job_id = _group_job_id(strategy_id, symbol) if strategy_id else f"strat_None_{symbol}"
    account_entries = _group_accounts.get(job_id, [])
    if not account_entries:
        logger.warning("Group job %s fired but has no accounts — skipping", job_id)
        return

    # ── Skip-hour / skip-weekday guard ───────────────────────────────────────
    if strategy_id and not bypass_skip_hours:
        from db.models import Strategy as _Strategy
        async with AsyncSessionLocal() as _db:
            _s = await _db.get(_Strategy, strategy_id)
        if _s and isinstance(getattr(_s, "id", None), int):
            _tz_str = _s.skip_hours_timezone or "UTC"
            try:
                _tz = ZoneInfo(_tz_str)
            except (ZoneInfoNotFoundError, TypeError, ValueError):
                _tz = ZoneInfo("UTC")
            _now = datetime.now(_tz)
            if _s.skip_hours:
                _skip_h: list[int] = json.loads(_s.skip_hours)
                if _now.hour in _skip_h:
                    logger.info("Skip hour %02d (%s): strategy_id=%s symbol=%s — skipped",
                                _now.hour, _tz_str, strategy_id, symbol)
                    return
            if _s.skip_weekdays:
                _skip_wd: list[int] = json.loads(_s.skip_weekdays)
                if _now.weekday() in _skip_wd:
                    logger.info("Skip weekday %s (%s): strategy_id=%s symbol=%s — skipped",
                                _now.strftime("%A"), _tz_str, strategy_id, symbol)
                    return

    # ── Load code strategy instance ──────────────────────────────────────────
    strategy_instance = None
    if module_path and class_name:
        try:
            mod = importlib.import_module(module_path)
            strategy_instance = getattr(mod, class_name)()
            if strategy_id:
                async with AsyncSessionLocal() as _db2:
                    from db.models import Strategy as _Strat
                    strat_db = await _db2.get(_Strat, strategy_id)
                    if strat_db and hasattr(strategy_instance, "apply_db_config"):
                        strategy_instance.apply_db_config(strat_db)
        except Exception:
            logger.exception("Failed to load strategy %s.%s — using LLM fallback",
                             module_path, class_name)

    is_abstract = strategy_instance is not None and hasattr(strategy_instance, "primary_tf")

    # ── Pre-flight: risk check all accounts before spending LLM tokens ────────
    try:
        async with AsyncSessionLocal() as db:
            clear_entries, blocked_entries = await _preflight_risk_check(
                account_entries, symbol, db
            )
    except Exception as exc:
        logger.exception("Group job %s pre-flight risk check failed: %s", job_id, exc)
        return

    if not clear_entries:
        logger.info(
            "Group job %s: all %d accounts risk-blocked — LLM skipped",
            job_id, len(account_entries),
        )
        return

    if blocked_entries:
        logger.info(
            "Group job %s: %d/%d accounts risk-blocked, proceeding for %d clear accounts",
            job_id, len(blocked_entries), len(account_entries), len(clear_entries),
        )

    # ── Phase 1: Primary account — full pipeline (OHLCV + LLM, fully traced) ──
    primary_account_id = clear_entries[0][0]
    ctx = None
    signal = None
    mt5_symbol = symbol

    try:
        if is_abstract:
            async with AsyncSessionLocal() as db:
                primary_account = await _get_primary_account(primary_account_id, db)
                if primary_account is None or not primary_account.is_active:
                    logger.error("Primary account %s not found or inactive for group job %s",
                                 primary_account_id, job_id)
                    return
            from services.abstract_runner import fetch_strategy_signal
            signal, market_data, mt5_symbol = await fetch_strategy_signal(
                symbol=symbol, timeframe=timeframe,
                strategy_instance=strategy_instance,
                primary_account=primary_account,
            )
            if signal is None:
                logger.warning("Group job %s: strategy returned no signal", job_id)
                return
        else:
            from services.ai_trading import StrategyOverrides
            primary_overrides = StrategyOverrides(**clear_entries[0][1])
            async with AsyncSessionLocal() as db:
                primary_result = await AITradingService().analyze_and_trade(
                    account_id=primary_account_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    db=db,
                    strategy_id=strategy_id,
                    strategy_overrides=primary_overrides,
                    strategy_instance=strategy_instance,
                )
            ctx = primary_result.shared_ctx
            if ctx is None:
                logger.warning(
                    "Group job %s: primary account %d returned no shared_ctx — skipping secondary accounts",
                    job_id, primary_account_id,
                )
                return
            logger.info("Group job %s Phase 1 done: action=%s order=%s",
                        job_id, primary_result.signal.action, primary_result.order_placed)

    except Exception as exc:
        logger.exception("Group job %s Phase 1 failed: %s", job_id, exc)
        return

    # ── Phase 2: Secondary accounts — execution only, shared context injected ─
    from services.ai_trading import StrategyOverrides
    for account_id, overrides_dict in clear_entries[1:]:
        overrides = StrategyOverrides(**overrides_dict)
        try:
            async with AsyncSessionLocal() as db:
                if is_abstract:
                    from services.abstract_runner import execute_abstract_for_account
                    sig, journal_id = await execute_abstract_for_account(
                        account_id=account_id, symbol=symbol, timeframe=timeframe,
                        signal=signal, mt5_symbol=mt5_symbol,
                        strategy_id=strategy_id, strategy_overrides=overrides, db=db,
                    )
                    logger.info("Group job done: account=%d symbol=%s action=%s",
                                account_id, symbol, sig.action if sig else "None")
                else:
                    result = await AITradingService().analyze_and_trade(
                        account_id=account_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        db=db,
                        strategy_id=strategy_id,
                        strategy_overrides=overrides,
                        shared_ctx=ctx,
                    )
                    logger.info("Group job done: account=%d symbol=%s action=%s order=%s",
                                account_id, symbol, result.signal.action, result.order_placed)
        except Exception as exc:
            logger.exception("Group job %s Phase 2 failed for account=%d: %s",
                             job_id, account_id, exc)
            # Continue to next account — one failure must not block others


def _add_binding_jobs(scheduler: AsyncIOScheduler, binding) -> None:
    """Register or update the group job for a single binding.

    If a group job for (strategy_id, symbol) already exists, the new account is
    appended to _group_accounts and the job is re-registered (replace_existing=True).
    """
    strategy = binding.strategy
    symbols = json.loads(strategy.symbols or "[]")
    _, overrides, _ = _build_overrides(strategy)
    module_path = strategy.module_path if strategy.execution_mode != "llm_only" else None
    class_name = strategy.class_name if strategy.execution_mode != "llm_only" else None
    trigger = _make_trigger(strategy)

    for symbol in symbols:
        job_id = _group_job_id(strategy.id, symbol)
        entry = (binding.account_id, overrides.model_dump())

        # Add account to group (avoid duplicates)
        existing = _group_accounts.get(job_id, [])
        if not any(acc_id == binding.account_id for acc_id, _ in existing):
            _group_accounts[job_id] = existing + [entry]
        else:
            # Update overrides for existing account
            _group_accounts[job_id] = [
                entry if acc_id == binding.account_id else (acc_id, ov)
                for acc_id, ov in existing
            ]

        scheduler.add_job(
            _run_group_strategy_job,
            trigger=trigger,
            id=job_id,
            args=[strategy.id, symbol, strategy.timeframe, module_path, class_name],
            replace_existing=True,
            misfire_grace_time=60,
        )
        logger.info("Group job registered/updated %s | accounts=%s",
                    job_id, [a for a, _ in _group_accounts[job_id]])


