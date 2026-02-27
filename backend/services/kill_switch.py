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
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_active: bool = False
_activation_reason: str | None = None
_activated_at: datetime | None = None
_lock: asyncio.Lock | None = None  # created lazily (event loop must exist)


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def is_active() -> bool:
    """Synchronous read — safe to call anywhere, including sync contexts."""
    return _active


def get_state() -> dict:
    """Return current kill switch state dict (safe to call synchronously)."""
    return {
        "is_active": _active,
        "reason": _activation_reason,
        "activated_at": _activated_at.isoformat() if _activated_at else None,
    }


async def activate(reason: str, triggered_by: str = "system") -> None:
    global _active, _activation_reason, _activated_at
    async with _get_lock():
        _active = True
        _activation_reason = reason
        _activated_at = datetime.now(UTC)
        logger.warning(
            "Kill switch ACTIVATED | triggered_by=%s | reason=%s",
            triggered_by,
            reason,
        )
        await _persist(action="activated", reason=reason, triggered_by=triggered_by)
        await _broadcast_kill_switch(reason=reason)
        await _send_kill_switch_alert(reason=reason)


async def deactivate(triggered_by: str = "user") -> None:
    global _active, _activation_reason, _activated_at
    async with _get_lock():
        _active = False
        _activation_reason = None
        _activated_at = None
        logger.warning(
            "Kill switch DEACTIVATED | triggered_by=%s",
            triggered_by,
        )
        await _persist(action="deactivated", reason=None, triggered_by=triggered_by)
        await _send_deactivation_alert()


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _persist(action: str, reason: str | None, triggered_by: str) -> None:
    """Persist kill switch event to PostgreSQL (best effort — never raises)."""
    try:
        from db.models import KillSwitchLog
        from db.postgres import AsyncSessionLocal

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


async def _send_kill_switch_alert(reason: str) -> None:
    """Send Telegram alert on kill switch activation (best effort — never raises)."""
    try:
        from services.alerting import send_alert

        await send_alert(f"*KILL SWITCH ACTIVATED*\nReason: {reason}")
    except Exception as exc:
        logger.error("Failed to send kill switch Telegram alert: %s", exc)


async def _send_deactivation_alert() -> None:
    """Send Telegram alert on kill switch deactivation (best effort — never raises)."""
    try:
        from services.alerting import send_alert

        await send_alert("*Kill switch DEACTIVATED* — trading resumed")
    except Exception as exc:
        logger.error("Failed to send deactivation Telegram alert: %s", exc)
