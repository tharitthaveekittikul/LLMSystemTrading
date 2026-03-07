"""MTFBacktestLoader — loads multiple MT5 CSV files and yields aligned MTFMarketData.

For each primary TF candle close at time T:
  - Primary TF: last N candles with close_time <= T
  - Each context TF: last N candles with close_time <= T
  No future data is ever included (strict <= T).
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Iterator

from services.mtf_data import OHLCV, MTFMarketData, TimeframeData
from services.mtf_csv_loader import load_mt5_csv

logger = logging.getLogger(__name__)


class MTFBacktestLoader:
    """Loads multiple MT5 CSV files and produces aligned MTFMarketData per primary-TF close."""

    def __init__(self, csv_sources: dict[str, str | io.StringIO]):
        """
        Args:
            csv_sources: dict mapping TF name -> file path (str) or StringIO object.
                         e.g. {"M15": "path/to/M15.csv", "H1": StringIO(...)}
        """
        self._all_candles: dict[str, list[OHLCV]] = {}
        for tf, source in csv_sources.items():
            if isinstance(source, str):
                from services.mtf_csv_loader import load_mt5_csv_from_path
                candles = load_mt5_csv_from_path(source)
            else:
                candles = load_mt5_csv(source)
            self._all_candles[tf] = candles
            logger.info("MTFBacktestLoader: loaded %d %s candles", len(candles), tf)

    def iter_primary_closes(
        self,
        primary_tf: str,
        context_tfs: list[str],
        candle_counts: dict[str, int],
        start_date: datetime,
        end_date: datetime,
    ) -> Iterator[MTFMarketData]:
        """Yield one MTFMarketData per primary-TF candle close in [start_date, end_date].

        All context TF candles returned have close_time <= trigger_time (no data leak).
        """
        if primary_tf not in self._all_candles:
            raise ValueError(f"Primary TF '{primary_tf}' not found in loaded CSVs")

        primary_candles = [
            c for c in self._all_candles[primary_tf]
            if start_date <= c.time <= end_date
        ]
        primary_count = candle_counts.get(primary_tf, 10)

        for trigger_candle in primary_candles:
            trigger_time = trigger_candle.time

            # Build primary TF window (last N candles up to and including trigger)
            primary_all = self._all_candles[primary_tf]
            primary_idx = next(
                (j for j, c in enumerate(primary_all) if c.time == trigger_time), None
            )
            if primary_idx is None:
                continue

            primary_window = primary_all[max(0, primary_idx - primary_count + 1): primary_idx + 1]

            # Build context TF windows
            timeframes: dict[str, TimeframeData] = {
                primary_tf: TimeframeData(tf=primary_tf, candles=list(primary_window))
            }

            for ctx_tf in context_tfs:
                if ctx_tf not in self._all_candles:
                    logger.warning("Context TF '%s' not in loaded CSVs — skipping", ctx_tf)
                    continue
                count = candle_counts.get(ctx_tf, 10)
                ctx_candles = [c for c in self._all_candles[ctx_tf] if c.time <= trigger_time]
                timeframes[ctx_tf] = TimeframeData(
                    tf=ctx_tf,
                    candles=ctx_candles[-count:] if ctx_candles else [],
                )

            current_price = trigger_candle.close
            yield MTFMarketData(
                symbol="",   # caller fills this in
                primary_tf=primary_tf,
                current_price=current_price,
                timeframes=timeframes,
                indicators={},   # BacktestEngine computes indicators
                trigger_time=trigger_time,
            )
