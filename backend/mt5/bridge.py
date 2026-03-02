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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

# Single-thread executor: MT5 initialize() binds to calling thread via COM.
# All MT5 calls must go through this same thread for the lifetime of the process.
_MT5_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")

try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore[assignment]
    MT5_AVAILABLE = False

logger = logging.getLogger(__name__)


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
        ok = await self.connect()
        if not ok:
            code, message = await self.get_last_error()
            await self.disconnect()
            raise ConnectionError(f"MT5 init failed (code {code}): {message}")
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _run(self, func, *args, **kwargs) -> Any:
        """Execute a synchronous MT5 call on the dedicated single MT5 thread."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_MT5_EXECUTOR, partial(func, *args, **kwargs))

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
        when a suffix is found and a WARNING when no match exists.

        Args:
            base: The bare symbol name (e.g. 'EURUSD').

        Returns:
            Resolved broker symbol (e.g. 'EURUSD.s'), or *base* if unresolved.
        """
        all_symbols = await self.get_symbols(market_watch_only=False)
        resolved = self.resolve_broker_symbol(base, all_symbols)
        if resolved != base:
            logger.info("Symbol resolved | %s → %s", base, resolved)
        else:
            logger.warning(
                "No broker match found for '%s' — using as-is. "
                "Available symbols sample (first 20): %s",
                base, all_symbols[:20],
            )
        return resolved

    # ── OHLCV ─────────────────────────────────────────────────────────────────

    async def get_rates(self, symbol: str, timeframe: int, count: int) -> list[dict]:
        """Fetch OHLCV candles. timeframe uses MT5 TIMEFRAME_* constants."""
        self._require_mt5()
        selected = await self._run(mt5.symbol_select, symbol, True)  # ensure symbol is in Market Watch
        if not selected:
            err = await self.get_last_error()
            logger.warning("symbol_select(%s) failed | error=%s", symbol, err)
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
