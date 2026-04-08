from __future__ import annotations
import importlib
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from db.postgres import AsyncSessionLocal
from services.ai_trading import AITradingService

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


async def _get_primary_account(account_id: int, db) -> "Account | None":
    """Load the first/primary account for Phase 1 signal generation."""
    from db.models import Account as _Account
    return await db.get(_Account, account_id)


async def _preflight_risk_check(
    account_entries: list[tuple[int, dict]],
    symbol: str,
    db,
) -> tuple[list[tuple[int, dict]], list[tuple[int, dict]]]:
    """Check risk limits for all accounts before calling LLM.

    Returns (clear_entries, blocked_entries).
    An account is clear if neither position limit nor rate limit is exceeded.
    """
    from db.models import Account as _Account
    from services.risk_manager import load_risk_config, check_position_limit, check_rate_limit
    from core.security import decrypt as _decrypt
    from mt5.bridge import AccountCredentials as _Creds, MT5Bridge as _Bridge
    from core.config import settings

    risk_cfg = await load_risk_config(db)
    clear: list[tuple[int, dict]] = []
    blocked: list[tuple[int, dict]] = []

    for account_id, overrides_dict in account_entries:
        account = await db.get(_Account, account_id)
        if not account or not account.is_active:
            blocked.append((account_id, overrides_dict))
            continue

        positions: list[dict] = []
        try:
            password = _decrypt(account.password_encrypted)
            creds = _Creds(
                login=account.login, password=password,
                server=account.server, path=account.mt5_path or settings.mt5_path,
            )
            async with _Bridge(creds) as b:
                raw = await b.get_positions()
            positions = [
                {"symbol": p.get("symbol", ""), "direction": "BUY" if p.get("type") == 0 else "SELL",
                 "volume": p.get("volume", 0), "profit": p.get("profit", 0)}
                for p in raw
            ]
        except Exception as exc:
            logger.warning("Pre-flight: could not fetch positions for account %d: %s", account_id, exc)

        exceeded_pos, pos_reason = check_position_limit(positions, risk_cfg)
        if exceeded_pos:
            logger.info("Pre-flight: account %d blocked by position limit — %s", account_id, pos_reason)
            blocked.append((account_id, overrides_dict))
            continue

        # NOTE: check_rate_limit tracks trades per-symbol globally (not per-account).
        # One busy account can block others on the same symbol. This is intentional as
        # a conservative safety measure to prevent the system from over-trading a symbol.
        exceeded_rate, rate_reason = await check_rate_limit(symbol, risk_cfg, db)
        if exceeded_rate:
            logger.info("Pre-flight: account %d blocked by rate limit — %s", account_id, rate_reason)
            blocked.append((account_id, overrides_dict))
            continue

        clear.append((account_id, overrides_dict))

    return clear, blocked


async def _run_group_strategy_job(
    strategy_id: int | None,
    symbol: str,
    timeframe: str,
    module_path: str | None = None,
    class_name: str | None = None,
) -> None:
    """Group job: compute signal once, execute per account.

    Reads account list from _group_accounts[job_id]. If the list is empty or the job
    has been removed, exits immediately.
    """
    from services.ai_trading import StrategyOverrides

    job_id = _group_job_id(strategy_id, symbol) if strategy_id else f"strat_None_{symbol}"
    account_entries = _group_accounts.get(job_id, [])
    if not account_entries:
        logger.warning("Group job %s fired but has no accounts — skipping", job_id)
        return

    # ── Skip-hour / skip-weekday guard ───────────────────────────────────────
    if strategy_id:
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


async def _run_strategy_job(
    account_id: int, symbol: str, timeframe: str,
    strategy_id: int | None, overrides,
    module_path: str | None = None,
    class_name: str | None = None,
) -> None:
    from db.postgres import AsyncSessionLocal
    from services.ai_trading import AITradingService

    # ── Skip-hour / skip-weekday guard ────────────────────────────────────────
    if strategy_id:
        from db.models import Strategy as _Strategy
        async with AsyncSessionLocal() as _db:
            _s = await _db.get(_Strategy, strategy_id)
        if _s:
            _tz_str = _s.skip_hours_timezone or "UTC"
            try:
                _tz = ZoneInfo(_tz_str)
            except ZoneInfoNotFoundError:
                _tz = ZoneInfo("UTC")
            _now = datetime.now(_tz)

            if _s.skip_hours:
                _skip_h: list[int] = json.loads(_s.skip_hours)
                if _now.hour in _skip_h:
                    logger.info(
                        "Skip hour %02d (%s): strategy_id=%s symbol=%s — candle skipped",
                        _now.hour, _tz_str, strategy_id, symbol,
                    )
                    return

            if _s.skip_weekdays:
                _skip_wd: list[int] = json.loads(_s.skip_weekdays)
                if _now.weekday() in _skip_wd:
                    _day_name = _now.strftime("%A")
                    logger.info(
                        "Skip weekday %s (%s): strategy_id=%s symbol=%s — candle skipped",
                        _day_name, _tz_str, strategy_id, symbol,
                    )
                    return
    # ─────────────────────────────────────────────────────────────────────────

    # Load code strategy instance fresh each run.
    strategy_instance = None
    if module_path and class_name:
        try:
            mod = importlib.import_module(module_path)
            strategy_instance = getattr(mod, class_name)()
        except Exception:
            logger.exception("Failed to load code strategy %s.%s — running LLM fallback",
                             module_path, class_name)

    # Detect whether the loaded instance is a new AbstractStrategy subclass
    # (identified by the presence of the `primary_tf` class attribute).
    is_abstract = strategy_instance is not None and hasattr(strategy_instance, "primary_tf")

    try:
        if is_abstract:
            # New path: AbstractStrategy.run(MTFMarketData) handles its own orchestration.
            from services.abstract_runner import run_abstract_strategy_pipeline
            async with AsyncSessionLocal() as db_session:
                from db.models import Strategy
                if strategy_id:
                    strat_db = await db_session.get(Strategy, strategy_id)
                    if strat_db and hasattr(strategy_instance, "apply_db_config"):
                        strategy_instance.apply_db_config(strat_db)

                signal, journal_id = await run_abstract_strategy_pipeline(
                    account_id=account_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    db=db_session,
                    strategy_id=strategy_id,
                    strategy_overrides=overrides,
                    strategy_instance=strategy_instance,
                )

            if signal:
                logger.info("Job done: account=%d symbol=%s action=%s",
                            account_id, symbol, signal.action)
        else:
            # Legacy path: use AITradingService (unchanged).
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
        logger.exception(
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
    from services.position_maintenance import PositionMaintenanceService
    from db.postgres import AsyncSessionLocal
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
        async def _run_news_fetch_job() -> None:
            async with AsyncSessionLocal() as _db:
                from services.news_fetcher import fetch_and_store_events
                try:
                    count = await fetch_and_store_events(_db)
                    logger.info("Scheduled news fetch complete | rows=%d", count)
                except Exception as exc:
                    logger.error("Scheduled news fetch failed: %s", exc)

        async def _run_news_analyze_job() -> None:
            async with AsyncSessionLocal() as _db:
                from services.news_analyzer import analyze_today_events
                try:
                    count = await analyze_today_events(_db)
                    logger.info("Scheduled news analysis complete | analyzed=%d", count)
                except Exception as exc:
                    logger.error("Scheduled news analysis failed: %s", exc)

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
        logger.info("News calendar jobs registered (fetch 23:00 UTC, analyze 00:00 UTC)")
    else:
        logger.info("News calendar jobs skipped (news_enabled=False)")

    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))


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
                args=[strategy.id, symbol, strategy.timeframe, module_path, class_name],
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info("Manually triggered group job %s", one_off_id)
        except Exception as e:
            logger.exception("Failed to trigger group job manually %s: %s", one_off_id, e)
