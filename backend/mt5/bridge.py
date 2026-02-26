"""MT5 Bridge — the ONLY module allowed to import MetaTrader5.

All broker interactions go through this class. MT5's Python library is
synchronous, so every call uses run_in_executor to avoid blocking FastAPI.
"""
import asyncio
import logging
from dataclasses import dataclass
from functools import partial
from typing import Any

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
        """Execute a synchronous MT5 call in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

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
        ok = await self._run(
            mt5.initialize,
            path=self._creds.path or None,
            login=self._creds.login,
            password=self._creds.password,
            server=self._creds.server,
        )
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

    # ── OHLCV ─────────────────────────────────────────────────────────────────

    async def get_rates(self, symbol: str, timeframe: int, count: int) -> list[dict]:
        """Fetch OHLCV candles. timeframe uses MT5 TIMEFRAME_* constants."""
        self._require_mt5()
        rates = await self._run(mt5.copy_rates_from_pos, symbol, timeframe, 0, count)
        if rates is None:
            return []
        import pandas as pd  # lazy import — only needed here

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.to_dict("records")

    # ── Tick data ─────────────────────────────────────────────────────────────

    async def get_tick(self, symbol: str) -> dict | None:
        self._require_mt5()
        tick = await self._run(mt5.symbol_info_tick, symbol)
        return tick._asdict() if tick else None

    # ── Order operations (used by executor.py only) ───────────────────────────

    async def send_order(self, request: dict) -> dict | None:
        self._require_mt5()
        result = await self._run(mt5.order_send, request)
        return result._asdict() if result else None

    async def get_last_error(self) -> tuple[int, str]:
        self._require_mt5()
        return await self._run(mt5.last_error)
