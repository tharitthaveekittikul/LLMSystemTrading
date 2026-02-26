"""Kill Switch — hard gate that blocks all order execution when active.

State is held in memory (fast read) and persisted to PostgreSQL for audit.
The switch must be checked inside mt5/executor.py before every order.

Usage:
    from services.kill_switch import is_active, activate, deactivate

    if is_active():
        return  # reject order

    await activate("Max drawdown exceeded")
"""
import asyncio
from datetime import datetime

_active: bool = False
_lock: asyncio.Lock | None = None  # created lazily (event loop must exist)


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def is_active() -> bool:
    """Synchronous read — safe to call anywhere, including sync contexts."""
    return _active


async def activate(reason: str, triggered_by: str = "system") -> None:
    global _active
    async with _get_lock():
        _active = True
        _log(action="activated", reason=reason, triggered_by=triggered_by)
        await _persist(action="activated", reason=reason, triggered_by=triggered_by)
        await _broadcast_kill_switch(reason=reason)


async def deactivate(triggered_by: str = "user") -> None:
    global _active
    async with _get_lock():
        _active = False
        _log(action="deactivated", reason=None, triggered_by=triggered_by)
        await _persist(action="deactivated", reason=None, triggered_by=triggered_by)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _log(action: str, reason: str | None, triggered_by: str) -> None:
    print(
        f"[KILL SWITCH] {action.upper()} at {datetime.utcnow().isoformat()} "
        f"by={triggered_by} reason={reason!r}"
    )


async def _persist(action: str, reason: str | None, triggered_by: str) -> None:
    """Persist kill switch event to PostgreSQL (best effort — never raises)."""
    try:
        from db.postgres import AsyncSessionLocal
        from db.models import KillSwitchLog

        async with AsyncSessionLocal() as session:
            log = KillSwitchLog(
                action=action,
                reason=reason,
                triggered_by=triggered_by,
            )
            session.add(log)
            await session.commit()
    except Exception as exc:
        print(f"[KILL SWITCH] Failed to persist log: {exc}")


async def _broadcast_kill_switch(reason: str) -> None:
    """Broadcast kill_switch_triggered event to all WebSocket clients."""
    try:
        from api.routes.ws import broadcast_all

        await broadcast_all("kill_switch_triggered", {"reason": reason})
    except Exception:
        pass
