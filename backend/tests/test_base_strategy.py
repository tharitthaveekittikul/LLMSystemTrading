import pytest
from types import SimpleNamespace
from strategies.base_strategy import BaseStrategy


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
    assert s.trigger_type == "candle_close"
    assert s.interval_minutes == 15


def test_abstract_requires_system_prompt():
    with pytest.raises(TypeError):
        BaseStrategy()


def test_should_trade_hold_returns_false():
    s = ConcreteStrategy()
    assert s.should_trade(SimpleNamespace(action="HOLD")) is False


def test_should_trade_buy_returns_true():
    s = ConcreteStrategy()
    assert s.should_trade(SimpleNamespace(action="BUY")) is True


def test_should_trade_sell_returns_true():
    s = ConcreteStrategy()
    assert s.should_trade(SimpleNamespace(action="SELL")) is True


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
