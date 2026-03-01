"""BacktestDataService — load historical OHLCV from MT5 or CSV.

MT5 path: requires a connected MT5Bridge (caller provides it).
CSV path: accepts a file-like object (StringIO or UploadFile.file).
"""
from __future__ import annotations

import io
import logging

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_CSV_COLUMNS = {"time", "open", "high", "low", "close", "tick_volume"}


class BacktestDataError(ValueError):
    """Raised when OHLCV data cannot be loaded or is invalid."""


class BacktestDataService:
    async def load_from_mt5(
        self,
        bridge,  # MT5Bridge instance (already connected)
        symbol: str,
        timeframe: int,
        date_from,
        date_to,
    ) -> list[dict]:
        """Fetch OHLCV candles from MT5 for the given date range.

        Returns list of dicts: time (datetime, UTC-aware), open, high, low,
        close, tick_volume.  Raises BacktestDataError on failure.
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
        logger.info(
            "Loaded %d candles from MT5 | %s", len(candles), symbol
        )
        return candles

    async def load_from_csv(self, file: io.StringIO | io.BytesIO) -> list[dict]:
        """Parse a CSV file into a list of OHLCV candle dicts.

        Expected CSV columns: time, open, high, low, close, tick_volume.
        'time' must be parseable by pandas (e.g. '2020-01-02 00:00:00').
        """
        try:
            df = pd.read_csv(file)
        except Exception as exc:
            raise BacktestDataError(f"Failed to parse CSV: {exc}") from exc

        df.columns = [c.strip().lower() for c in df.columns]
        missing = REQUIRED_CSV_COLUMNS - set(df.columns)
        if missing:
            raise BacktestDataError(f"Missing columns in CSV: {sorted(missing)}")

        try:
            df["time"] = pd.to_datetime(df["time"], utc=True)
        except Exception as exc:
            raise BacktestDataError(f"Cannot parse 'time' column: {exc}") from exc

        df = df.sort_values("time").reset_index(drop=True)
        logger.info("Loaded %d candles from CSV", len(df))
        return df[["time", "open", "high", "low", "close", "tick_volume"]].to_dict("records")
