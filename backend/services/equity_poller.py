"""Equity Snapshot Poller — background task that polls MT5 and persists equity to QuestDB.

Started as an asyncio.Task in main.py lifespan. Runs every 60 seconds.
Broadcasts equity_update WebSocket events after each poll.
Each account's failure is isolated — one bad account won't stop polling of others.
Skips polling during Forex market close (Fri 22:00 UTC → Sun 22:00 UTC).
"""
import asyncio
import logging
from datetime import UTC, datetime

from core.config import settings
from core.security import decrypt
from db.postgres import AsyncSessionLocal
from mt5.bridge import AccountCredentials, MT5Bridge
from services.risk_manager import check_drawdown, load_risk_config

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 60  # seconds


def _forex_market_open(now: datetime) -> bool:
    """Return True if the Forex market is open.

    Forex is open Mon 00:00 UTC → Fri 22:00 UTC (approximately).
    weekday(): 0=Monday … 4=Friday, 5=Saturday, 6=Sunday.
    """
    weekday = now.weekday()
    hour = now.hour
    if weekday == 5:  # Saturday — always closed
        return False
    if weekday == 6 and hour < 22:  # Sunday before 22:00 UTC — closed
        return False
    if weekday == 4 and hour >= 22:  # Friday from 22:00 UTC — closed
        return False
    return True


async def run_equity_poller() -> None:
    """Background loop — runs forever until task is cancelled."""
    logger.info("Equity poller started | interval=%ds", _POLL_INTERVAL)
    while True:
        now = datetime.now(UTC)
        if _forex_market_open(now):
            try:
                await _poll_all_accounts()
            except Exception as exc:
                logger.error("Equity poller cycle error: %s", exc)
        else:
            logger.debug(
                "Equity poller skipped — market closed | weekday=%d hour=%d UTC",
                now.weekday(), now.hour,
            )
        await asyncio.sleep(_POLL_INTERVAL)


async def _poll_all_accounts() -> None:
    from db.postgres import AsyncSessionLocal
    from db.models import Account
    from db.questdb import insert_equity_snapshot
    from api.routes.ws import broadcast
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Account).where(Account.is_active == True)  # noqa: E712
        )
        # Convert to plain dicts while the session is still open
        accounts_data = [
            {
                "id": a.id,
                "login": a.login,
                "password_encrypted": a.password_encrypted,
                "server": a.server,
                "mt5_path": a.mt5_path,
            }
            for a in result.scalars().all()
        ]

    for account_data in accounts_data:
        await _poll_account(account_data, insert_equity_snapshot, broadcast)


async def _poll_account(account, insert_fn, broadcast_fn) -> None:
    """Poll a single account — catch all errors so other accounts keep running.

    ``account`` is a plain dict with keys: id, login, password_encrypted, server, mt5_path.
    """
    try:
        password = decrypt(account["password_encrypted"])
        creds = AccountCredentials(
            login=account["login"],
            password=password,
            server=account["server"],
            path=account["mt5_path"] or settings.mt5_path,
        )
        async with MT5Bridge(creds) as bridge:
            info = await bridge.get_account_info()

        if not info:
            logger.warning("Equity poller: no account info | account_id=%s", account["id"])
            return

        equity = float(info.get("equity", 0))
        balance = float(info.get("balance", 0))
        margin = float(info.get("margin", 0))
        free_margin = float(info.get("margin_free", 0))
        margin_level = float(info.get("margin_level", 0))
        currency = info.get("currency", "USD")

        # ── Drawdown monitor ─────────────────────────────────────────────────
        from services.kill_switch import is_active, activate  # local import avoids circular

        if not is_active():
            async with AsyncSessionLocal() as _db:
                risk_cfg = await load_risk_config(_db)
            exceeded, reason = check_drawdown(equity, balance, risk_cfg)
            if exceeded:
                await activate(reason, triggered_by="equity_poller")

        await insert_fn(
            account_id=account["id"],
            equity=equity,
            balance=balance,
            margin=margin,
        )

        await broadcast_fn(account["id"], "equity_update", {
            "account_id": account["id"],
            "balance": balance,
            "equity": equity,
            "margin": margin,
            "free_margin": free_margin,
            "margin_level": margin_level,
            "currency": currency,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        logger.debug("Equity polled | account_id=%s equity=%.2f", account["id"], equity)
    except Exception as exc:
        logger.error("Equity poller failed for account_id=%s: %s", account["id"], exc)
