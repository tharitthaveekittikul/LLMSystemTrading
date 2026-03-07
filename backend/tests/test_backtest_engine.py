"""Tests for BacktestEngine — event-loop simulation with synthetic OHLCV data."""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest


def _make_candles(n: int, base_price: float = 1.10000) -> list[dict]:
    """Generate n synthetic M15 candles with a mild uptrend."""
    candles = []
    t = datetime(2020, 1, 2, tzinfo=timezone.utc)
    price = base_price
    for _ in range(n):
        candles.append({
            "time": t,
            "open": price,
            "high": price + 0.00050,
            "low": price - 0.00030,
            "close": price + 0.00010,
            "tick_volume": 100,
        })
        price += 0.00001
        t += timedelta(minutes=15)
    return candles


def _always_buy_strategy():
    """Strategy that always returns BUY with 20-pip SL and 40-pip TP."""
    m = MagicMock()
    def signal(market_data):
        price = market_data["current_price"]
        return {
            "action": "BUY",
            "entry": price,
            "stop_loss": round(price - 0.0020, 5),
            "take_profit": round(price + 0.0040, 5),
            "confidence": 0.9,
            "rationale": "always buy",
            "timeframe": "M15",
        }
    m.generate_signal.side_effect = signal
    m.strategy_type = "code"
    return m


def _always_hold_strategy():
    m = MagicMock()
    m.generate_signal.return_value = {"action": "HOLD", "entry": 0,
                                       "stop_loss": 0, "take_profit": 0,
                                       "confidence": 0.5, "rationale": "", "timeframe": "M15"}
    m.strategy_type = "code"
    return m


async def test_engine_returns_expected_keys():
    from services.backtest_engine import BacktestEngine
    engine = BacktestEngine()
    result = await engine.run(
        _make_candles(60),
        _always_buy_strategy(),
        {"symbol": "EURUSD", "timeframe": "M15", "initial_balance": 10_000.0,
         "spread_pips": 1.0, "execution_mode": "close_price", "volume": 0.1, "max_llm_calls": 0},
        progress_cb=None,
    )
    assert "trades" in result
    assert "equity_curve" in result
    assert isinstance(result["trades"], list)
    assert isinstance(result["equity_curve"], list)


async def test_hold_strategy_produces_no_trades():
    from services.backtest_engine import BacktestEngine
    engine = BacktestEngine()
    result = await engine.run(
        _make_candles(60),
        _always_hold_strategy(),
        {"symbol": "EURUSD", "timeframe": "M15", "initial_balance": 10_000.0,
         "spread_pips": 0.0, "execution_mode": "close_price", "volume": 0.1, "max_llm_calls": 0},
        progress_cb=None,
    )
    assert result["trades"] == []


async def test_sl_closes_position_intra_candle():
    """When candle low crosses SL, position closes with exit_reason='sl'."""
    from services.backtest_engine import BacktestEngine

    # Candle 0–49: build window (price ~1.10)
    # Candle 50: BUY signal at ~1.10050, SL = 1.09850, TP = 1.10450
    # Candle 51: low = 1.097 < SL → closes at SL
    base_candles = _make_candles(50)
    signal_candle = {
        "time": datetime(2020, 1, 3, tzinfo=timezone.utc),
        "open": 1.10050, "high": 1.10100, "low": 1.10000, "close": 1.10050,
        "tick_volume": 100,
    }
    sl_candle = {
        "time": datetime(2020, 1, 3, 0, 15, tzinfo=timezone.utc),
        "open": 1.10050, "high": 1.10060, "low": 1.09700, "close": 1.09750,
        "tick_volume": 100,
    }
    candles = base_candles + [signal_candle, sl_candle]

    strategy = MagicMock()
    call_count = [0]
    def signal_fn(market_data):
        call_count[0] += 1
        price = market_data["current_price"]
        return {
            "action": "BUY",
            "entry": price,
            "stop_loss": round(price - 0.0020, 5),
            "take_profit": round(price + 0.0040, 5),
            "confidence": 0.9,
            "rationale": "buy",
            "timeframe": "M15",
        }
    strategy.generate_signal.side_effect = signal_fn
    strategy.strategy_type = "code"

    engine = BacktestEngine()
    result = await engine.run(
        candles, strategy,
        {"symbol": "EURUSD", "timeframe": "M15", "initial_balance": 10_000.0,
         "spread_pips": 0.0, "execution_mode": "intra_candle", "volume": 0.1, "max_llm_calls": 0},
        progress_cb=None,
    )
    sl_trades = [t for t in result["trades"] if t.get("exit_reason") == "sl"]
    assert len(sl_trades) >= 1


async def test_progress_callback_called():
    """Progress callback is invoked during long runs."""
    from services.backtest_engine import BacktestEngine

    calls = []
    async def progress(pct: int):
        calls.append(pct)

    engine = BacktestEngine()
    await engine.run(
        _make_candles(2100),
        _always_buy_strategy(),
        {"symbol": "EURUSD", "timeframe": "M15", "initial_balance": 10_000.0,
         "spread_pips": 0.0, "execution_mode": "close_price", "volume": 0.1, "max_llm_calls": 0},
        progress_cb=progress,
    )
    assert len(calls) >= 1  # at least one progress update for 2100 candles


async def test_end_of_data_closes_open_position():
    """An open position at the last candle is closed with exit_reason='end_of_data'."""
    from services.backtest_engine import BacktestEngine

    # Use 60 candles — enough for window, strategy always buys
    # TP is very far away so it won't be hit naturally
    strategy = MagicMock()
    def far_tp_signal(market_data):
        price = market_data["current_price"]
        return {
            "action": "BUY",
            "entry": price,
            "stop_loss": round(price - 0.5000, 5),   # very wide SL
            "take_profit": round(price + 1.0000, 5),  # very far TP
            "confidence": 0.9,
            "rationale": "hold forever",
            "timeframe": "M15",
        }
    strategy.generate_signal.side_effect = far_tp_signal
    strategy.strategy_type = "code"

    engine = BacktestEngine()
    result = await engine.run(
        _make_candles(60), strategy,
        {"symbol": "EURUSD", "timeframe": "M15", "initial_balance": 10_000.0,
         "spread_pips": 0.0, "execution_mode": "close_price", "volume": 0.1, "max_llm_calls": 0},
        progress_cb=None,
    )
    end_trades = [t for t in result["trades"] if t.get("exit_reason") == "end_of_data"]
    assert len(end_trades) == 1


async def test_engine_accepts_rule_only_strategy():
    """BacktestEngine works with an AbstractStrategy subclass using run() interface."""
    from services.backtest_engine import BacktestEngine
    from strategies.base_strategy import RuleOnlyStrategy, StrategyResult

    class BuyStrategy(RuleOnlyStrategy):
        primary_tf = "M15"
        context_tfs = ["H1"]
        symbols = ["EURUSD"]
        def check_rule(self, md):
            return StrategyResult(
                action="BUY", entry=md.current_price,
                stop_loss=md.current_price - 0.002,
                take_profit=md.current_price + 0.004,
                confidence=0.9, rationale="test", timeframe="M15",
            )
        def analytics_schema(self): return {}

    engine = BacktestEngine()
    result = await engine.run(
        _make_candles(60),
        BuyStrategy(),
        {"symbol": "EURUSD", "timeframe": "M15", "initial_balance": 10_000.0,
         "spread_pips": 1.0, "execution_mode": "close_price", "volume": 0.1, "max_llm_calls": 0},
        progress_cb=None,
    )
    assert "trades" in result
