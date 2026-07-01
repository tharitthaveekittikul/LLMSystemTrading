"""Data classes for the backtest engine: open position state and closed-trade results."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OpenPosition:
    symbol: str
    direction: str          # "BUY" | "SELL"
    entry_time: int         # unix timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    volume: float
    take_profit_levels: list[float] | None = None
    tp_level_idx: int = 0
    pattern_name: str | None = None
    pattern_metadata: str | None = None


@dataclass
class TradeResult:
    symbol: str
    direction: str
    entry_time: int
    entry_price: float
    stop_loss: float
    take_profit: float
    volume: float
    exit_time: int
    exit_price: float
    exit_reason: str
    profit: float
    equity_after: float
    pattern_name: str | None = None
    pattern_metadata: str | None = None
    source: str | None = None
