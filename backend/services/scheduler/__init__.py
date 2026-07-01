"""Scheduler — registers and runs group strategy jobs, position maintenance, and news jobs.

Public surface — matches the old services/scheduler.py module exactly.
`_group_accounts` is re-exported too: tests reach into it directly via
`services.scheduler._group_accounts[job_id] = [...]` — since dict mutation
through any name bound to the same object is visible everywhere the object
is shared, this stays correct as long as no submodule ever *rebinds*
`_group_accounts` to a new dict (all real usages are subscript/`.pop()`
mutations of the one dict created in _state.py).
"""
from services.scheduler._group_job import _run_group_strategy_job
from services.scheduler._lifecycle import (
    add_binding_jobs,
    remove_all_binding_jobs,
    remove_binding_jobs,
    reschedule_maintenance_job,
    reschedule_news_jobs,
    start_scheduler,
    stop_scheduler,
    trigger_binding_manually,
)
from services.scheduler._risk import _get_primary_account, _preflight_risk_check
from services.scheduler._state import (
    CANDLE_CRON,
    _group_accounts,
    _group_bindings_by_strategy,
    _group_job_id,
    _make_trigger,
    _scheduler,
    get_scheduler,
)

__all__ = [
    "CANDLE_CRON",
    "_get_primary_account",
    "_group_accounts",
    "_group_bindings_by_strategy",
    "_group_job_id",
    "_make_trigger",
    "_preflight_risk_check",
    "_run_group_strategy_job",
    "_scheduler",
    "add_binding_jobs",
    "get_scheduler",
    "remove_all_binding_jobs",
    "remove_binding_jobs",
    "reschedule_maintenance_job",
    "reschedule_news_jobs",
    "start_scheduler",
    "stop_scheduler",
    "trigger_binding_manually",
]
