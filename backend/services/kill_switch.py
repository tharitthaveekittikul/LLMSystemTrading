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
import logging

logger = logging.getLogger(__name__)

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
        logger.warning(
            "Kill switch ACTIVATED | triggered_by=%s | reason=%s",
            triggered_by,
            reason,
        )
        await _persist(action="activated", reason=reason, triggered_by=triggered_by)
        await _broadcast_kill_switch(reason=reason)


async def deactivate(triggered_by: str = "user") -> None:
    global _active
    async with _get_lock():
        _active = False
        logger.warning(
            "Kill switch DEACTIVATED | triggered_by=%s",
            triggered_by,
        )
        await _persist(action="deactivated", reason=None, triggered_by=triggered_by)


# ── Internal helpers ──────────────────────────────────────────────────────────

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
        logger.error("Failed to persist kill switch log: %s", exc)


async def _broadcast_kill_switch(reason: str) -> None:
    """Broadcast kill_switch_triggered event to all WebSocket clients."""
    try:
        from api.routes.ws import broadcast_all

        await broadcast_all("kill_switch_triggered", {"reason": reason})
    except Exception as exc:
        logger.error("Failed to broadcast kill switch event: %s", exc)
