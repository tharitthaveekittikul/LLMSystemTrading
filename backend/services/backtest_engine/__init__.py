"""Backtest simulation engine.

Public surface — matches the old services/backtest_engine.py module exactly.
"""
from services.backtest_engine._engine import BacktestEngine
from services.backtest_engine._models import OpenPosition, TradeResult

__all__ = [
    "BacktestEngine",
    "OpenPosition",
    "TradeResult",
]
