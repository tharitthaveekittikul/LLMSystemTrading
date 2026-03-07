"""Multi-timeframe market data structures.

MTFMarketData replaces the old single-TF market_data dict throughout the strategy system.
Strategies declare primary_tf and context_tfs; the engine fetches only what is declared.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OHLCV:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int


@dataclass
class TimeframeData:
    tf: str
    candles: list[OHLCV]   # sorted oldest→newest; newest = most recently CLOSED candle


@dataclass
class MTFMarketData:
    symbol: str
    primary_tf: str                          # triggers on this TF close
    current_price: float
    timeframes: dict[str, TimeframeData]     # {"H1": ..., "M15": ..., "M1": ...}
    indicators: dict[str, float]             # computed on primary_tf candles
    trigger_time: datetime                   # UTC time of primary candle close
