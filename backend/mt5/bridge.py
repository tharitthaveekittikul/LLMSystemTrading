"""MT5 Bridge — the ONLY module allowed to import MetaTrader5.

All broker interactions go through this class. MT5's Python library is
synchronous, so every call uses run_in_executor to avoid blocking FastAPI.

Thread-safety note (from MT5 docs):
  mt5.initialize() binds to the calling OS thread via COM. Every subsequent
  mt5.* call MUST run on that SAME thread. The default asyncio thread pool
  can dispatch to any worker — so we use a dedicated single-thread executor
  (_MT5_EXECUTOR) to guarantee all MT5 calls stay on one thread.
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

# Single-thread executor: MT5 initialize() binds to calling thread via COM.
# All MT5 calls must go through this same thread for the lifetime of the process.
_MT5_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")

# Global lock: only one MT5Bridge context may be active at a time.
# mt5.shutdown() kills the entire session immediately — if two bridges overlap
# (e.g. a strategy job + maintenance job firing concurrently), one bridge's
# shutdown() will destroy the other's live session, causing copy_rates_from_pos
# to return None for all retries (~15 s timeout before 502).
_MT5_LOCK = asyncio.Lock()

# Module-level cache of resolved broker symbols for the current MT5 session.
# get_broker_symbol() previously re-fetched the entire broker symbol universe
# on every call from 4+ call sites. Cleared in disconnect() since a different
# broker/account may expose a different symbol universe on the next session.
_SYMBOL_CACHE: dict[str, str] = {}

try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore[assignment]
    MT5_AVAILABLE = False

logger = logging.getLogger(__name__)


class SessionBusyError(RuntimeError):
    """Raised when a different account holds the warm MT5 session pinned.

    MT5 only supports one broker login per process — a pinned session (e.g.
    a live dashboard poller) can't be silently swapped out from under it.
    """


@dataclass
class _LiveSession:
    """The one warm MT5 login this process currently holds, if any."""
    key: tuple[int, str]  # (login, server)
    connected: bool = True
    last_used: float = 0.0
    pin_count: int = 0


# Warm-session cache: connect once, reuse across consecutive `async with
# MT5Bridge(creds)` calls for the same account instead of a full
# initialize()/shutdown() handshake every time (was previously happening on
# every equity poll tick and every account sync — ~800 connect/disconnect
# cycles in a 6h window). Reused/torn down under _MT5_LOCK so a reap or
# account swap never races a live call burst.
_live: _LiveSession | None = None
_IDLE_TIMEOUT = 300.0  # seconds of no use before the reaper shuts it down
_REAPER_INTERVAL = 30.0  # seconds between idle checks
_reaper_task: asyncio.Task | None = None


async def _run_on_mt5_thread(func, *args, **kwargs) -> Any:
    """Execute a synchronous MT5 call on the dedicated single MT5 thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_MT5_EXECUTOR, partial(func, *args, **kwargs))


def _ensure_reaper() -> None:
    """Start the idle-session reaper if it isn't already running.

    Must be called with _MT5_LOCK held (i.e. from inside _acquire_session).
    """
    global _reaper_task
    if _reaper_task is None or _reaper_task.done():
        _reaper_task = asyncio.create_task(_reap_idle_session(), name="mt5_session_reaper")


async def _reap_idle_session() -> None:
    """Shut down the warm session once it's been idle past _IDLE_TIMEOUT.

    Exits after reaping (rather than looping forever) — a new one is started
    lazily by _ensure_reaper() the next time a session is established.
    """
    global _live
    while True:
        await asyncio.sleep(_REAPER_INTERVAL)
        async with _MT5_LOCK:
            if _live is None:
                return
            if _live.pin_count > 0:
                continue
            if time.monotonic() - _live.last_used <= _IDLE_TIMEOUT:
                continue
            if MT5_AVAILABLE:
                await _run_on_mt5_thread(mt5.shutdown)
            logger.info(
                "MT5 warm session reaped after %.0fs idle | login=%s",
                _IDLE_TIMEOUT, _live.key[0],
            )
            _live = None
            return


@dataclass
class AccountCredentials:
    login: int
    password: str
    server: str
    path: str = ""  # path to terminal64.exe, empty = use default installation


class MT5Bridge:
    """Stateless bridge for a single MT5 account.

    Usage:
        async with MT5Bridge(creds) as bridge:
            info = await bridge.get_account_info()
    """

    def __init__(self, credentials: AccountCredentials) -> None:
        self._creds = credentials

    async def __aenter__(self) -> "MT5Bridge":
        await _MT5_LOCK.acquire()
        try:
            ok = await self._acquire_session()
        except Exception:
            _MT5_LOCK.release()
            raise
        if not ok:
            code, message = await self.get_last_error()
            _MT5_LOCK.release()
            raise ConnectionError(f"MT5 init failed (code {code}): {message}")
        return self

    async def __aexit__(self, *_: Any) -> None:
        try:
            if _live is not None:
                _live.last_used = time.monotonic()
        finally:
            _MT5_LOCK.release()

    async def _acquire_session(self) -> bool:
        """Reuse the warm MT5 session for this bridge's account, or connect.

        Must be called with _MT5_LOCK held. Returns True once a live session
        for this bridge's (login, server) is active — reused if already warm,
        freshly connected otherwise. Raises SessionBusyError if a different
        account is pinned (see pin_session).
        """
        global _live
        key = (self._creds.login, self._creds.server)

        if _live is not None and _live.connected:
            if _live.key == key:
                _live.last_used = time.monotonic()
                return True
            if _live.pin_count > 0:
                raise SessionBusyError(
                    f"MT5 session pinned to login={_live.key[0]} — "
                    f"cannot switch to login={key[0]}"
                )
            logger.info(
                "MT5 session swap | from_login=%s to_login=%s", _live.key[0], key[0]
            )
            if MT5_AVAILABLE:
                await _run_on_mt5_thread(mt5.shutdown)
            _live = None

        ok = await self.connect()
        if not ok:
            return False
        _live = _LiveSession(key=key, last_used=time.monotonic())
        _ensure_reaper()
        return True

    @classmethod
    async def pin_session(cls, credentials: AccountCredentials) -> None:
        """Establish (if needed) and pin the warm session to *credentials*.

        Pinning prevents both the idle reaper and other callers requesting a
        different account from tearing down or swapping this session out —
        used by the demand-driven dashboard poller, which needs the session
        to stay up for the life of the poll loop, not just one burst.
        """
        global _live
        bridge = cls(credentials)
        async with _MT5_LOCK:
            ok = await bridge._acquire_session()
            if not ok:
                code, message = await bridge.get_last_error()
                raise ConnectionError(f"MT5 init failed (code {code}): {message}")
            assert _live is not None
            _live.pin_count += 1

    @classmethod
    async def unpin_session(cls) -> None:
        """Release a pin taken by pin_session(). Safe to call if already unpinned."""
        global _live
        async with _MT5_LOCK:
            if _live is not None and _live.pin_count > 0:
                _live.pin_count -= 1

    @classmethod
    async def invalidate(cls) -> None:
        """Mark the warm session dead so the next __aenter__ reconnects.

        Call this when a caller detects the broker side has silently dropped
        (e.g. terminal_info().connected == False) rather than leaving the
        stale session cached for everyone else to fail against too.
        """
        global _live
        async with _MT5_LOCK:
            if _live is not None:
                _live.connected = False

    @classmethod
    async def force_shutdown(cls) -> None:
        """Tear down the warm session and stop the reaper (app shutdown)."""
        global _live, _reaper_task
        async with _MT5_LOCK:
            if _reaper_task is not None:
                _reaper_task.cancel()
                _reaper_task = None
            if _live is not None and _live.connected and MT5_AVAILABLE:
                await _run_on_mt5_thread(mt5.shutdown)
            _live = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _run(self, func, *args, **kwargs) -> Any:
        """Execute a synchronous MT5 call on the dedicated single MT5 thread."""
        return await _run_on_mt5_thread(func, *args, **kwargs)

    def _require_mt5(self) -> None:
        if not MT5_AVAILABLE:
            raise RuntimeError(
                "MetaTrader5 package is not installed. "
                "Run: uv sync --extra mt5  (Windows only)"
            )

    # ── Connection ────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        self._require_mt5()
        logger.info("Connecting to MT5 | login=%s server=%s", self._creds.login, self._creds.server)
        kwargs: dict = {
            "login": self._creds.login,
            "password": self._creds.password,
            "server": self._creds.server,
        }
        if self._creds.path:
            kwargs["path"] = self._creds.path
        ok = await self._run(mt5.initialize, **kwargs)
        if ok:
            logger.info("MT5 connected | login=%s", self._creds.login)
        else:
            err = await self.get_last_error()
            logger.error("MT5 connect failed | login=%s | error=%s", self._creds.login, err)
        return ok

    async def disconnect(self) -> None:
        if MT5_AVAILABLE:
            await self._run(mt5.shutdown)
            logger.info("MT5 disconnected | login=%s", self._creds.login)
        _SYMBOL_CACHE.clear()

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_info(self) -> dict | None:
        self._require_mt5()
        info = await self._run(mt5.account_info)
        return info._asdict() if info else None

    # ── Positions ─────────────────────────────────────────────────────────────

    async def get_positions(self, symbol: str | None = None) -> list[dict]:
        self._require_mt5()
        if symbol:
            raw = await self._run(mt5.positions_get, symbol=symbol)
        else:
            raw = await self._run(mt5.positions_get)
        return [p._asdict() for p in raw] if raw else []

    async def get_orders(self, symbol: str | None = None) -> list[dict]:
        """Fetch pending (unfilled) orders. Returns empty list if none."""
        self._require_mt5()
        if symbol:
            raw = await self._run(mt5.orders_get, symbol=symbol)
        else:
            raw = await self._run(mt5.orders_get)
        return [o._asdict() for o in raw] if raw else []

    # ── Symbols ───────────────────────────────────────────────────────────────

    async def get_symbols(self, market_watch_only: bool = True) -> list[str]:
        """Return available symbol names.

        Args:
            market_watch_only: If True (default), return only symbols currently
                visible in Market Watch. If False, return all broker symbols.
        """
        self._require_mt5()
        raw = await self._run(mt5.symbols_get)
        if not raw:
            return []
        if market_watch_only:
            return [s.name for s in raw if s.visible]
        return [s.name for s in raw]

    @staticmethod
    def resolve_broker_symbol(base: str, broker_symbols: list[str]) -> str:
        """Find the broker's actual symbol name for a bare name like 'EURUSD'.

        Brokers commonly add suffixes or prefixes to instrument names
        (e.g. 'EURUSD.s', 'EURUSDm', 'GOLD.raw'). This method resolves the
        bare strategy symbol to the name the connected broker actually exposes.

        Matching priority (first match wins):
            1. Exact match          — 'EURUSD'  in broker_symbols
            2. Shortest prefix      — broker symbol starts with base name
            3. Shortest substring   — base name appears anywhere in broker symbol
            4. Return base unchanged (caller should log a warning)

        Args:
            base: The bare symbol name stored in the strategy config.
            broker_symbols: Full list of symbols returned by the broker.

        Returns:
            The resolved broker symbol, or *base* if no match is found.
        """
        if base in broker_symbols:
            return base

        # Priority 2: prefix match (e.g. EURUSD.s, EURUSDm)
        prefix_matches = [s for s in broker_symbols if s.startswith(base)]
        if prefix_matches:
            return min(prefix_matches, key=len)

        # Priority 3: substring / suffix match (e.g. XAU → XAUUSD.s)
        sub_matches = [s for s in broker_symbols if base in s]
        if sub_matches:
            return min(sub_matches, key=len)

        return base

    async def get_broker_symbol(self, base: str) -> str:
        """Return the broker-specific symbol name for a bare base name.

        Fetches all available symbols (including those not in Market Watch)
        and delegates to :meth:`resolve_broker_symbol`.  Logs an INFO message
        when a suffix is found and a WARNING only when the symbol genuinely
        can't be confirmed.

        Cached per MT5 session in ``_SYMBOL_CACHE`` (cleared on disconnect) —
        this was previously called fresh from 4+ call sites, each re-fetching
        the entire broker symbol universe just to resolve one name.

        Args:
            base: The bare symbol name (e.g. 'EURUSD').

        Returns:
            Resolved broker symbol (e.g. 'EURUSD.s'), or *base* if unresolved.
        """
        cached = _SYMBOL_CACHE.get(base)
        if cached is not None:
            return cached

        # mt5.symbols_get() only reliably lists symbols that have been through
        # symbol_select() at least once this terminal session (lazy population
        # — the project's own docs flag this quirk for tick data; it applies
        # here too). Select the exact name first so a genuinely valid symbol
        # isn't missed just because this connection hasn't touched it yet —
        # otherwise get_rates()'s own symbol_select() succeeds moments later
        # and returns real candles, while this method warns "no match" first.
        selected = await self._run(mt5.symbol_select, base, True)

        all_symbols = await self.get_symbols(market_watch_only=False)
        resolved = self.resolve_broker_symbol(base, all_symbols)
        if resolved != base:
            logger.info("Symbol resolved | %s → %s", base, resolved)
        elif selected:
            # symbol_select succeeded on the bare name itself — it's a valid,
            # tradable symbol; symbols_get() just hadn't enumerated it yet.
            logger.debug(
                "Symbol '%s' confirmed via symbol_select (not yet enumerated by symbols_get)",
                base,
            )
        else:
            logger.warning(
                "No broker match found for '%s' — using as-is. "
                "Available symbols sample (first 20): %s",
                base, all_symbols[:20],
            )
        _SYMBOL_CACHE[base] = resolved
        return resolved

    # ── OHLCV ─────────────────────────────────────────────────────────────────

    async def get_rates(self, symbol: str, timeframe: int, count: int, require_connected: bool = True) -> list[dict]:
        """Fetch OHLCV candles. timeframe uses MT5 TIMEFRAME_* constants.

        Set require_connected=False to allow fetching from local MT5 cache even when
        the terminal reports connected=False (e.g. fresh per-request connections for charts).
        """
        self._require_mt5()
        if require_connected:
            info = await self._run(mt5.terminal_info)
            if info and not info.connected:
                logger.warning("MT5 not connected to broker — skipping get_rates(%s, tf=%s)", symbol, timeframe)
                return []
        selected = await self._run(mt5.symbol_select, symbol, True)  # ensure symbol is in Market Watch
        if not selected:
            err = await self.get_last_error()
            logger.warning("symbol_select(%s) failed | error=%s", symbol, err)
        rates = await self._run(mt5.copy_rates_from_pos, symbol, timeframe, 0, count)
        if rates is None:
            # MT5 may need time to populate the buffer (e.g. right after candle close
            # or symbol_select activation). Retry with increasing back-off.
            logger.warning("copy_rates_from_pos(%s, tf=%s) returned None — retrying after 2 s", symbol, timeframe)
            await asyncio.sleep(2)
            rates = await self._run(mt5.copy_rates_from_pos, symbol, timeframe, 0, count)
        if rates is None:
            logger.warning("copy_rates_from_pos(%s, tf=%s) still None — retrying after 5 s", symbol, timeframe)
            await asyncio.sleep(5)
            rates = await self._run(mt5.copy_rates_from_pos, symbol, timeframe, 0, count)
        logger.debug("copy_rates_from_pos(%s, tf=%s, count=%s) -> %s rows", symbol, timeframe, count, len(rates) if rates is not None else "None")
        if rates is None:
            return []
        import pandas as pd  # lazy import — only needed here

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.to_dict("records")

    async def get_rates_range(
        self,
        symbol: str,
        timeframe: int,
        date_from: "datetime",
        date_to: "datetime",
    ) -> list[dict]:
        """Fetch OHLCV candles between two UTC datetimes.

        Uses copy_rates_range — designed for large historical datasets (backtesting).
        Returns list of dicts with keys: time (UTC-aware datetime), open, high, low,
        close, tick_volume.
        """
        self._require_mt5()
        selected = await self._run(mt5.symbol_select, symbol, True)
        if not selected:
            err = await self.get_last_error()
            logger.warning("symbol_select(%s) failed | error=%s", symbol, err)
            raise RuntimeError(
                f"symbol_select({symbol!r}) failed (error={err}). "
                "In MT5: View → Market Watch → right-click → Show All, "
                f"find '{symbol}', right-click → Request (download history), then retry."
            )
        rates = await self._run(mt5.copy_rates_range, symbol, timeframe, date_from, date_to)
        logger.debug(
            "copy_rates_range(%s, tf=%s, %s → %s) -> %s rows",
            symbol,
            timeframe,
            date_from,
            date_to,
            len(rates) if rates is not None else "None",
        )
        if rates is None:
            return []
        import pandas as pd  # lazy import — same pattern as get_rates

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.to_dict("records")

    # ── Tick data ─────────────────────────────────────────────────────────────

    async def get_tick(self, symbol: str) -> dict | None:
        self._require_mt5()
        await self._run(mt5.symbol_select, symbol, True)  # ensure symbol is in Market Watch
        tick = await self._run(mt5.symbol_info_tick, symbol)
        return tick._asdict() if tick else None

    async def get_symbol_info(self, symbol: str) -> dict | None:
        """Return symbol info dict (trade_tick_value, trade_tick_size, etc.)."""
        self._require_mt5()
        await self._run(mt5.symbol_select, symbol, True)
        info = await self._run(mt5.symbol_info, symbol)
        return info._asdict() if info else None

    async def is_market_open(self, symbol: str) -> tuple[bool, str]:
        """Return (is_open, trade_mode_name) based on the symbol's current trade_mode.

        trade_mode values (MT5 constants):
            0  SYMBOL_TRADE_MODE_DISABLED   — trading disabled
            1  SYMBOL_TRADE_MODE_LONGONLY   — buy orders only
            2  SYMBOL_TRADE_MODE_SHORTONLY  — sell orders only
            3  SYMBOL_TRADE_MODE_CLOSEONLY  — only closing existing positions
            4  SYMBOL_TRADE_MODE_FULL       — full two-way trading (market open)

        Returns True only for FULL (4) since only that mode allows opening new positions.
        """
        self._require_mt5()
        await self._run(mt5.symbol_select, symbol, True)
        info = await self._run(mt5.symbol_info, symbol)
        if info is None:
            return False, "unavailable"
        mode_names = {0: "disabled", 1: "long_only", 2: "short_only", 3: "close_only", 4: "full"}
        trade_mode = info.trade_mode
        mode_name = mode_names.get(trade_mode, f"unknown({trade_mode})")
        return trade_mode == mt5.SYMBOL_TRADE_MODE_FULL, mode_name

    # ── Order operations (used by executor.py only) ───────────────────────────

    async def get_filling_mode(self, symbol: str) -> int:
        """Return the best ORDER_FILLING_* mode supported by the broker for symbol.

        MT5 brokers expose a bitmask in ``symbol_info().filling_mode``:
            bit 0  (1)  → ORDER_FILLING_FOK   (Fill-or-Kill)
            bit 1  (2)  → ORDER_FILLING_IOC   (Immediate-or-Cancel)
            bit 2  (4)  → ORDER_FILLING_RETURN (partial fills allowed, common on CFD/Forex)

        Picks in priority order: FOK → IOC → RETURN.
        Falls back to RETURN (2 in MT5 enum) if info is unavailable.
        """
        self._require_mt5()
        info = await self._run(mt5.symbol_info, symbol)
        if not info:
            logger.warning("symbol_info(%s) unavailable — defaulting to RETURN filling", symbol)
            return mt5.ORDER_FILLING_RETURN

        mask = info.filling_mode
        if mask & 1:   # FOK supported
            return mt5.ORDER_FILLING_FOK
        if mask & 2:   # IOC supported
            return mt5.ORDER_FILLING_IOC
        # RETURN (mask & 4) or unknown — RETURN is the safest default for Forex/CFD
        return mt5.ORDER_FILLING_RETURN

    async def modify_position_sltp(
        self,
        ticket: int,
        symbol: str,
        new_sl: float,
        new_tp: float,
    ) -> dict | None:
        """Modify the SL/TP of an existing open position.

        Uses TRADE_ACTION_SLTP (value 6) which does NOT require a price or deviation.
        Returns the order_send result dict, or None on MT5 API failure.
        """
        self._require_mt5()
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": new_sl,
            "tp": new_tp,
            "magic": 20250101,
        }
        result = await self._run(partial(mt5.order_send, **request))
        return result._asdict() if result else None

    async def send_order(self, request: dict) -> dict | None:

        self._require_mt5()
        result = await self._run(partial(mt5.order_send, **request))
        return result._asdict() if result else None

    async def get_last_error(self) -> tuple[int, str]:
        self._require_mt5()
        return await self._run(mt5.last_error)

    async def is_autotrading_enabled(self) -> bool:
        """Return True if the MT5 terminal has AutoTrading switched ON.

        MT5 enforces this at the terminal level — if disabled, every
        order_send() call fails with 'AutoTrading disabled by client'
        regardless of broker connection or account permissions.

        Enable it via the toolbar ▶ AutoTrading button (turns green) or
        Tools → Options → Expert Advisors → Allow automated trading.
        """
        self._require_mt5()
        info = await self._run(mt5.terminal_info)
        return bool(info and info.trade_allowed)

    async def is_broker_connected(self) -> bool:
        """Check terminal→broker connection (mt5.terminal_info().connected).

        Use this as a lightweight heartbeat during polling to detect a dropped
        broker connection without waiting for a data-fetch failure.
        """
        self._require_mt5()
        info = await self._run(mt5.terminal_info)
        return bool(info and info.connected)

    # ── History ───────────────────────────────────────────────────────────────

    async def history_deals_get(self, date_from: datetime, date_to: datetime) -> list[dict]:
        """Fetch all closed deals in [date_from, date_to].

        Each deal is one fill leg. A completed position produces two deals
        sharing the same position_id: one DEAL_ENTRY_IN (entry=0) and one
        DEAL_ENTRY_OUT (entry=1). The OUT deal carries the realised profit.
        """
        self._require_mt5()
        deals = await self._run(mt5.history_deals_get, date_from, date_to)
        logger.debug("history_deals_get(%s → %s) -> %s deals", date_from, date_to, len(deals) if deals else 0)
        return [d._asdict() for d in deals] if deals else []

    async def history_orders_get(self, date_from: datetime, date_to: datetime) -> list[dict]:
        """Fetch all historical orders in [date_from, date_to].

        Note: orders and deals are distinct in MT5. An order is the instruction;
        a deal is the resulting fill. Each filled order produces one or more
        deals. Use history_deals_get for realised P&L and position reconstruction.
        """
        self._require_mt5()
        orders = await self._run(mt5.history_orders_get, date_from, date_to)
        logger.debug("history_orders_get(%s → %s) -> %s orders", date_from, date_to, len(orders) if orders else 0)
        return [o._asdict() for o in orders] if orders else []
