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
from dataclasses import dataclass, field
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
    last_position_tickets: set[int] = field(default_factory=set)
    last_account_info: dict | None = None  # cached from last poll cycle
    _initialized: bool = False  # skip first-cycle diff (no baseline yet)


_states: dict[int, AccountPollState] = {}
_tasks:  dict[int, asyncio.Task]     = {}


def get_states() -> dict[int, AccountPollState]:
    return _states


async def start_account(account_id: int) -> None:
    """Start a persistent poll session for account_id (no-op if already running).

    MT5 Python library is a per-process singleton — only one account can be
    connected at a time. Stop any other running pollers before starting a new one.
    """
    if account_id in _tasks and not _tasks[account_id].done():
        return

    # Stop all other running pollers before starting — MT5 only supports one connection.
    for other_id in list(_tasks.keys()):
        if other_id != account_id and not _tasks[other_id].done():
            logger.info("MT5 poller: stopping account_id=%s to switch to account_id=%s", other_id, account_id)
            await stop_account(other_id)

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
            logger.exception(
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
    from mt5.bridge import AccountCredentials, MT5Bridge

    state = _states.setdefault(account_id, AccountPollState(account_id=account_id))
    # Reset on each new session so a reconnect doesn't diff against stale tickets
    state._initialized = False
    state.last_position_tickets = set()

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

    state.last_error = None
    logger.info("MT5 connected for polling | account_id=%s login=%s", account_id, account.login)

    # MT5 terminal needs a moment to (re)establish broker connection after initialize().
    # This is especially likely when a fresh MT5Bridge was used just before the poller
    # started (e.g. /accounts/info calls on page load). Wait up to 15 s.
    for _attempt in range(15):
        if await bridge.is_broker_connected():
            break
        if _attempt == 0:
            logger.info("Waiting for broker connection | account_id=%s", account_id)
        await asyncio.sleep(1)
    else:
        await bridge.disconnect()
        raise ConnectionError("Broker did not connect within 15 s of MT5 initialize()")

    # Pre-populate cache immediately so /accounts/{id}/info can serve from it
    # before the first poll cycle completes (avoids a competing fresh bridge).
    info = await bridge.get_account_info()
    if info:
        state.last_account_info = info

    # Mark connected only after broker is confirmed and cache is ready.
    # The /accounts/{id}/info endpoint checks is_connected + last_account_info together.
    state.is_connected = True

    try:
        while True:
            # Heartbeat: detect broker connection drop before fetching data.
            if not await bridge.is_broker_connected():
                raise ConnectionError("Broker connection lost (terminal_info.connected=False)")
            just_closed = await _fetch_and_broadcast(account_id, bridge, state)
            if just_closed:
                await _sync_history_with_bridge(account_id, bridge)
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await bridge.disconnect()
        state.is_connected = False
        logger.info("MT5 disconnected | account_id=%s", account_id)


async def _fetch_and_broadcast(account_id: int, bridge, state: AccountPollState) -> set[int]:
    """Fetch MT5 data, broadcast to WebSocket clients, and return any just-closed ticket IDs."""
    from api.routes.ws import broadcast, get_watched_symbols

    info = await bridge.get_account_info()
    positions = await bridge.get_positions()
    pending_orders = await bridge.get_orders()

    if info:
        state.last_account_info = info
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
        "positions": [{**_normalize_position(p), "account_id": account_id} for p in positions],
    })

    # Include broker server time so the frontend can calibrate against local clock drift.
    broker_time_iso: str
    symbols = [o.get("symbol") for o in pending_orders if o.get("symbol")] or \
              [p.get("symbol") for p in positions if p.get("symbol")]
    broker_time_iso = datetime.now(UTC).isoformat()  # fallback
    if symbols:
        try:
            tick = await bridge.get_tick(symbols[0])
            if tick:
                broker_time_iso = datetime.fromtimestamp(tick["time"], UTC).isoformat()
        except Exception:
            pass

    await broadcast(account_id, "pending_orders_update", {
        "account_id": account_id,
        "orders": [_normalize_order(o) for o in pending_orders],
        "broker_time": broker_time_iso,
    })

    # Live price for any symbol a connected chart is currently watching
    # (e.g. the trading-chart page) — one extra get_tick call per watched symbol.
    for watched_symbol in get_watched_symbols(account_id):
        try:
            tick = await bridge.get_tick(watched_symbol)
        except Exception:
            tick = None
        if tick:
            await broadcast(account_id, "tick_update", {
                "symbol": watched_symbol,
                "bid": tick.get("bid"),
                "ask": tick.get("ask"),
                "time": tick.get("time"),
            })

    # Detect closed positions (tickets present last cycle but gone now)
    current_tickets = {p.get("ticket") for p in positions if p.get("ticket")}
    just_closed: set[int] = set()
    if state._initialized:
        just_closed = state.last_position_tickets - current_tickets
        if just_closed:
            logger.info(
                "Detected %d closed position(s) | account_id=%s tickets=%s",
                len(just_closed), account_id, just_closed,
            )
    else:
        state._initialized = True

    state.last_position_tickets = current_tickets
    state.last_polled_at = datetime.now(UTC)
    logger.debug(
        "Polled | account_id=%s positions=%d pending_orders=%d",
        account_id, len(positions), len(pending_orders),
    )
    return just_closed


async def _sync_history_with_bridge(account_id: int, bridge) -> None:
    """Sync closed deals using the already-open bridge — no new MT5 connection created."""
    from datetime import timedelta

    from db.models import Account
    from db.postgres import AsyncSessionLocal
    from services.history_sync import HistoryService

    date_to = datetime.now(UTC)
    date_from = date_to - timedelta(days=2)
    try:
        deals = await bridge.history_deals_get(date_from, date_to)
        if not deals:
            return
        async with AsyncSessionLocal() as db:
            account = await db.get(Account, account_id)
            if not account:
                logger.warning("History sync: account not found | account_id=%s", account_id)
                return
            svc = HistoryService()
            result = await svc.sync_deals_to_db(account, deals, db)
            logger.info(
                "History sync complete | account_id=%s imported=%s updated=%s",
                account_id, result["imported"], result["updated"],
            )
    except Exception:
        logger.exception("History sync failed | account_id=%s", account_id)


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


# MT5 ORDER_TYPE_* constants for pending orders:
#   2 = BUY_LIMIT, 3 = SELL_LIMIT, 4 = BUY_STOP, 5 = SELL_STOP
#   6 = BUY_STOP_LIMIT, 7 = SELL_STOP_LIMIT
_ORDER_TYPE_NAMES: dict[int, str] = {
    2: "buy_limit",
    3: "sell_limit",
    4: "buy_stop",
    5: "sell_stop",
    6: "buy_stop_limit",
    7: "sell_stop_limit",
}


def _normalize_order(order: dict) -> dict:
    expiry_ts = order.get("time_expiration", 0)
    return {
        "ticket":       order.get("ticket"),
        "symbol":       order.get("symbol"),
        "type":         _ORDER_TYPE_NAMES.get(order.get("type", -1), "unknown"),
        "volume":       order.get("volume_current"),
        "price":        order.get("price_open"),
        "sl":           order.get("sl") or None,
        "tp":           order.get("tp") or None,
        "placed_time":  datetime.fromtimestamp(order.get("time_setup", 0), UTC).isoformat(),
        "expiration":   datetime.fromtimestamp(expiry_ts, UTC).isoformat() if expiry_ts else None,
    }
