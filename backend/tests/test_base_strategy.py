"""Tests for the legacy BaseStrategy (strategies.base) and the AbstractStrategy alias.

The old concrete BaseStrategy lives in strategies.base and provides the legacy
lot_size / sl_pips / tp_pips / news_filter / generate_signal interface.

strategies.base_strategy.BaseStrategy is now an alias for AbstractStrategy
(the new typed hierarchy).  The alias is tested here for import-compatibility
only; full new-hierarchy tests live in test_strategy_base.py.
"""
import pytest

# ── Legacy base (strategies.base) — still the concrete class with old interface ──
from strategies.base import BaseStrategy


class ConcreteStrategy(BaseStrategy):
    symbols = ["EURUSD"]
    timeframe = "M15"

    def system_prompt(self) -> str:
        return "You are a test strategy."


def test_symbols():
    assert ConcreteStrategy().symbols == ["EURUSD"]


def test_defaults():
    s = ConcreteStrategy()
    assert s.lot_size() is None
    assert s.sl_pips() is None
    assert s.tp_pips() is None
    assert s.news_filter() is True


def test_abstract_requires_run_and_analytics_schema():
    """AbstractStrategy (new hierarchy) cannot be instantiated without run() + analytics_schema()."""
    from strategies.base_strategy import AbstractStrategy

    class Incomplete(AbstractStrategy):
        pass

    with pytest.raises(TypeError):
        Incomplete()


def test_generate_signal_default_returns_none():
    s = ConcreteStrategy()
    assert s.generate_signal({}) is None


def test_eurusd_scalp_is_valid_strategy():
    from strategies.eurusd_m15_scalp import EURUSDScalp
    s = EURUSDScalp()
    assert s.symbols == ["EURUSD", "GBPUSD"]
    assert s.timeframe == "M15"
    assert s.trigger_type == "candle_close"
    assert len(s.system_prompt()) > 20
    assert s.lot_size() == 0.05
    assert s.sl_pips() == 15
    assert s.tp_pips() is None   # not set, uses account default
    assert s.news_filter() is True
