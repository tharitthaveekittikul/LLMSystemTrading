"""MT5 Poller — demand-driven, per-account, persistent connection.

Lifecycle per account:
  start_account(id)  →  connect once  →  poll loop  →  disconnect
  stop_account(id)   →  cancel task   →  finally: disconnect

MT5 Python library is global state (one terminal, one login at a time).
Only one account should be polled at a time, which the WS route enforces
by calling start_account only when the first client connects.

Polling vs events: MT5 Python lib has no push callbacks — polling is the
only option. Keeping the connection persistent (connect once, poll N times)
is far cheaper than reconnecting every cycle.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5.0   # seconds between data fetches
RETRY_DELAY   = 30.0  # seconds before retrying after a connection failure


@dataclass
class AccountPollState:
    account_id: int
    is_connected: bool = False
    last_polled_at: datetime | None = None
    last_error: str | None = None


_states: dict[int, AccountPollState] = {}
_tasks:  dict[int, asyncio.Task]     = {}


def get_states() -> dict[int, AccountPollState]:
    return _states


async def start_account(account_id: int) -> None:
    """Start a persistent poll session for account_id (no-op if already running)."""
    if account_id in _tasks and not _tasks[account_id].done():
        return
    _tasks[account_id] = asyncio.create_task(
        _poll_loop(account_id), name=f"mt5_poller_{account_id}"
    )
    logger.info("MT5 poller started | account_id=%s", account_id)


async def stop_account(account_id: int) -> None:
    """Cancel the poll task for account_id (MT5 disconnects in the task's finally block)."""
    task = _tasks.pop(account_id, None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if account_id in _states:
        _states[account_id].is_connected = False
    logger.info("MT5 poller stopped | account_id=%s", account_id)


# ── Internal ──────────────────────────────────────────────────────────────────

async def _poll_loop(account_id: int) -> None:
    """Outer loop: connect, poll until failure, retry after RETRY_DELAY."""
    while True:
        try:
            await _poll_session(account_id)
        except asyncio.CancelledError:
            raise  # let stop_account's task.cancel() propagate
        except Exception as exc:
            state = _states.get(account_id)
            if state:
                state.is_connected = False
                state.last_error = str(exc)
            logger.error(
                "Poll session ended | account_id=%s | retry in %.0fs | %s",
                account_id, RETRY_DELAY, exc,
            )
            await asyncio.sleep(RETRY_DELAY)


async def _poll_session(account_id: int) -> None:
    """Connect once, fetch data on every interval until cancelled or error."""
    from core.config import settings
    from core.security import decrypt
    from db.models import Account
    from db.postgres import AsyncSessionLocal
    from mt5.bridge import MT5Bridge, AccountCredentials

    state = _states.setdefault(account_id, AccountPollState(account_id=account_id))

    async with AsyncSessionLocal() as session:
        account = await session.get(Account, account_id)

    if not account or not account.is_active:
        logger.warning("Poller: account not found | account_id=%s", account_id)
        return

    creds = AccountCredentials(
        login=account.login,
        password=decrypt(account.password_encrypted),
        server=account.server,
        path=account.mt5_path or settings.mt5_path,
    )

    bridge = MT5Bridge(creds)
    ok = await bridge.connect()
    if not ok:
        code, msg = await bridge.get_last_error()
        await bridge.disconnect()
        raise ConnectionError(f"MT5 init failed (code {code}): {msg}")

    state.is_connected = True
    state.last_error = None
    logger.info("MT5 connected for polling | account_id=%s login=%s", account_id, account.login)

    try:
        while True:
            # Heartbeat: detect broker connection drop before fetching data.
            if not await bridge.is_broker_connected():
                raise ConnectionError("Broker connection lost (terminal_info.connected=False)")
            await _fetch_and_broadcast(account_id, bridge, state)
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await bridge.disconnect()
        state.is_connected = False
        logger.info("MT5 disconnected | account_id=%s", account_id)


async def _fetch_and_broadcast(account_id: int, bridge, state: AccountPollState) -> None:
    from api.routes.ws import broadcast

    info = await bridge.get_account_info()
    positions = await bridge.get_positions()

    if info:
        await broadcast(account_id, "equity_update", {
            "account_id": account_id,
            "balance":      info.get("balance"),
            "equity":       info.get("equity"),
            "margin":       info.get("margin"),
            "free_margin":  info.get("margin_free"),
            "margin_level": info.get("margin_level"),
            "currency":     info.get("currency"),
            "timestamp":    datetime.now(UTC).isoformat(),
        })

    await broadcast(account_id, "positions_update", {
        "account_id": account_id,
        "positions": [_normalize_position(p) for p in positions],
    })

    state.last_polled_at = datetime.now(UTC)
    logger.debug("Polled | account_id=%s positions=%d", account_id, len(positions))


def _normalize_position(pos: dict) -> dict:
    return {
        "ticket":        pos.get("ticket"),
        "symbol":        pos.get("symbol"),
        "type":          "buy" if pos.get("type") == 0 else "sell",
        "volume":        pos.get("volume"),
        "open_price":    pos.get("price_open"),
        "current_price": pos.get("price_current"),
        "sl":            pos.get("sl") or None,
        "tp":            pos.get("tp") or None,
        "profit":        pos.get("profit"),
        "swap":          pos.get("swap"),
        "open_time":     datetime.fromtimestamp(pos.get("time", 0), UTC).isoformat(),
    }
