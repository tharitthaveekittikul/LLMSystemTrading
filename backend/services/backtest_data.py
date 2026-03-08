"""BacktestDataService — load historical OHLCV from MT5 or CSV.

MT5 path: requires a connected MT5Bridge (caller provides it).
CSV path: accepts MT5 tab-delimited export format (angle-bracket headers).
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


class BacktestDataError(ValueError):
    """Raised when OHLCV data cannot be loaded or is invalid."""


class BacktestDataService:
    async def load_from_mt5(
        self,
        bridge,
        symbol: str,
        timeframe: int,
        date_from,
        date_to,
    ) -> list[dict]:
        """Fetch OHLCV candles from MT5 for the given date range.

        Returns list of dicts: time, open, high, low, close, tick_volume, spread.
        """
        try:
            candles = await bridge.get_rates_range(symbol, timeframe, date_from, date_to)
        except Exception as exc:
            raise BacktestDataError(f"MT5 fetch failed: {exc}") from exc

        if not candles:
            raise BacktestDataError(
                f"No data returned for {symbol} {date_from} → {date_to}. "
                "Check that the symbol is available in Market Watch and MT5 has history downloaded."
            )
        logger.info("Loaded %d candles from MT5 | %s", len(candles), symbol)
        return candles

    async def load_from_csv(self, file: io.StringIO | io.BytesIO) -> list[dict]:
        """Parse an MT5 tab-delimited CSV into a list of OHLCV candle dicts.

        Expects MT5 export format:
          <DATE>  <TIME>  <OPEN>  <HIGH>  <LOW>  <CLOSE>  <TICKVOL>  <VOL>  <SPREAD>
          2017.01.02  00:00:00  1.10000  ...

        Returns dicts with keys: time, open, high, low, close, tick_volume, spread.
        Raises BacktestDataError on parse failure.
        """
        from services.mtf_csv_loader import load_mt5_csv, MTFCSVError

        try:
            ohlcv_list = load_mt5_csv(file)
        except MTFCSVError as exc:
            raise BacktestDataError(str(exc)) from exc

        candles = [
            {
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "tick_volume": c.tick_volume,
                "spread": c.spread,
            }
            for c in ohlcv_list
        ]
        logger.info("Loaded %d candles from CSV", len(candles))
        return candles
