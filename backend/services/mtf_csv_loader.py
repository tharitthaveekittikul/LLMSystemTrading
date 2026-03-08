"""Load MT5 export CSV files into OHLCV lists.

MT5 exports bar data as tab-separated CSV with angle-bracket column headers:
  <DATE>  <TIME>  <OPEN>  <HIGH>  <LOW>  <CLOSE>  <TICKVOL>  <VOL>  <SPREAD>
  2017.01.02  00:00:00  143.878  ...

load_mt5_csv() handles the MT5 format specifically.
load_mt5_csv_from_path() is a convenience wrapper that opens the file.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import pandas as pd

from services.mtf_data import OHLCV

logger = logging.getLogger(__name__)

_REQUIRED = {"date", "time", "open", "high", "low", "close", "tickvol"}


class MTFCSVError(ValueError):
    """Raised when an MT5 CSV cannot be parsed."""


def load_mt5_csv(file: io.StringIO | io.BytesIO) -> list[OHLCV]:
    """Parse an MT5 bar-export CSV into a list of OHLCV objects.

    Strips angle brackets from column names, combines <DATE>+<TIME> into UTC datetime.
    Returns candles sorted oldest→newest.
    """
    try:
        df = pd.read_csv(file, sep="\t")
    except Exception as exc:
        raise MTFCSVError(f"Failed to read CSV: {exc}") from exc

    # Normalise column names: strip <>, lowercase, strip whitespace
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]

    missing = _REQUIRED - set(df.columns)
    if missing:
        raise MTFCSVError(f"Missing columns in MT5 CSV: {sorted(missing)}. Got: {list(df.columns)}")

    try:
        df["datetime"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["time"].astype(str),
            format="%Y.%m.%d %H:%M:%S",
            utc=True,
        )
    except Exception as exc:
        raise MTFCSVError(f"Cannot parse date/time columns: {exc}") from exc

    df = df.sort_values("datetime").reset_index(drop=True)

    candles = [
        OHLCV(
            time=row.datetime.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            tick_volume=int(row.tickvol),
            spread=int(getattr(row, "spread", 0) or 0),
        )
        for row in df.itertuples()
    ]
    logger.info("Loaded %d candles from MT5 CSV", len(candles))
    return candles


def load_mt5_csv_from_path(path: str) -> list[OHLCV]:
    """Convenience: open file at path and call load_mt5_csv()."""
    with open(path, "r", encoding="utf-8") as f:
        return load_mt5_csv(io.StringIO(f.read()))
