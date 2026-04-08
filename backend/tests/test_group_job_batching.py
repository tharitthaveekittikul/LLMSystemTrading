"""Tests for group job batching — single LLM call across multiple accounts."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── SharedMarketContext tests ─────────────────────────────────────────────────

def test_shared_market_context_fields():
    from services.ai_trading import SharedMarketContext
    from ai.orchestrator import TradingSignal

    signal = TradingSignal(
        action="BUY", entry=1.1, stop_loss=1.09, take_profit=1.12,
        confidence=0.8, rationale="test", timeframe="H1",
    )
    ctx = SharedMarketContext(
        symbol="EURUSD",
        mt5_symbol="EURUSD.r",
        timeframe="H1",
        candles=[{"close": 1.1}],
        indicators={"rsi_14": 55.0},
        current_price=1.1,
        signal=signal,
        llm_result=None,
        news_signal=None,
    )
    assert ctx.symbol == "EURUSD"
    assert ctx.signal.action == "BUY"
    assert ctx.llm_result is None


@pytest.mark.asyncio
async def test_fetch_strategy_signal_returns_result_and_market_data():
    """fetch_strategy_signal() should call strategy.run() once and return (signal, data, symbol)."""
    from services.abstract_runner import fetch_strategy_signal
    from strategies.base_strategy import StrategyResult
    from services.mtf_data import MTFMarketData, TimeframeData, OHLCV

    fake_signal = StrategyResult(
        action="BUY", entry=1900.0, stop_loss=1880.0, take_profit=1940.0,
        confidence=0.9, rationale="pattern", timeframe="H1",
    )

    mock_strategy = AsyncMock()
    mock_strategy.primary_tf = "H1"
    mock_strategy.context_tfs = []
    mock_strategy.candle_counts = {"H1": 20}
    mock_strategy.run = AsyncMock(return_value=fake_signal)

    mock_account = MagicMock()
    mock_account.login = 123
    mock_account.password_encrypted = b"enc"
    mock_account.server = "demo"
    mock_account.mt5_path = None

    fake_ohlcv = [{"time": 1700000000 + i * 3600, "open": 1900.0, "high": 1910.0,
                   "low": 1890.0, "close": 1905.0, "tick_volume": 50} for i in range(30)]

    with patch("services.abstract_runner.decrypt", return_value="pass"), \
         patch("services.abstract_runner.MT5Bridge") as MockBridge:

        bridge_instance = AsyncMock()
        bridge_instance.get_broker_symbol = AsyncMock(return_value="XAUUSD.r")
        bridge_instance.get_tick = AsyncMock(return_value={"ask": 1906.0, "bid": 1904.0})
        bridge_instance.get_rates = AsyncMock(return_value=fake_ohlcv)
        MockBridge.return_value.__aenter__ = AsyncMock(return_value=bridge_instance)
        MockBridge.return_value.__aexit__ = AsyncMock(return_value=False)

        signal, market_data, mt5_symbol = await fetch_strategy_signal(
            symbol="XAUUSD",
            timeframe="H1",
            strategy_instance=mock_strategy,
            primary_account=mock_account,
        )

    assert signal is not None
    assert signal.action == "BUY"
    assert mt5_symbol == "XAUUSD.r"
    assert market_data is not None
    mock_strategy.run.assert_awaited_once()


def test_group_bindings_by_strategy_groups_correctly():
    """Bindings sharing the same strategy_id should be grouped together."""
    from services.scheduler import _group_bindings_by_strategy

    def make_binding(binding_id, account_id, strategy_id, symbols, timeframe="H1"):
        b = MagicMock()
        b.id = binding_id
        b.account_id = account_id
        b.strategy.id = strategy_id
        b.strategy.symbols = f'["{symbols}"]'
        b.strategy.timeframe = timeframe
        b.strategy.trigger_type = "cron"
        b.strategy.interval_minutes = None
        b.strategy.execution_mode = "llm_only"
        b.strategy.module_path = None
        b.strategy.class_name = None
        b.strategy.lot_size = 0.1
        b.strategy.sl_pips = 20.0
        b.strategy.tp_pips = 40.0
        b.strategy.news_filter = True
        b.strategy.custom_prompt = None
        return b

    bindings = [
        make_binding(1, 101, 10, "EURUSD"),
        make_binding(2, 102, 10, "EURUSD"),
        make_binding(3, 103, 20, "XAUUSD"),
    ]

    groups = _group_bindings_by_strategy(bindings)

    assert len(groups) == 2
    group_key_10 = (10, "EURUSD")
    assert group_key_10 in groups
    assert len(groups[group_key_10]["account_entries"]) == 2
    account_ids = [e[0] for e in groups[group_key_10]["account_entries"]]
    assert 101 in account_ids and 102 in account_ids
    group_key_20 = (20, "XAUUSD")
    assert group_key_20 in groups
    assert len(groups[group_key_20]["account_entries"]) == 1


@pytest.mark.asyncio
async def test_run_group_strategy_job_skips_llm_when_all_accounts_blocked():
    """If all accounts are risk-blocked, AITradingService must NOT be called."""
    import services.scheduler as sched_module

    job_id = "strat_10_EURUSD"
    sched_module._group_accounts[job_id] = [
        (101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
        (102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
    ]

    with patch("services.scheduler._preflight_risk_check", new_callable=AsyncMock,
               return_value=([], [(101, {}), (102, {})])), \
         patch("services.ai_trading.AITradingService.analyze_and_trade",
               new_callable=AsyncMock) as mock_analyze, \
         patch("services.scheduler.AsyncSessionLocal"):

        await sched_module._run_group_strategy_job(
            strategy_id=10, symbol="EURUSD", timeframe="H1",
            module_path=None, class_name=None,
        )

    mock_analyze.assert_not_awaited()
    del sched_module._group_accounts[job_id]


@pytest.mark.asyncio
async def test_run_group_strategy_job_executes_only_clear_accounts():
    """If one account is blocked and one is clear, AITradingService runs once (primary only)."""
    import services.scheduler as sched_module

    job_id = "strat_10_EURUSD"
    sched_module._group_accounts[job_id] = [
        (101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
        (102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
    ]

    from ai.orchestrator import TradingSignal
    from services.ai_trading import SharedMarketContext, AnalysisResult

    fake_signal = TradingSignal(action="HOLD", entry=0.0, stop_loss=0.0, take_profit=0.0,
                                confidence=0.5, rationale="test", timeframe="H1")
    fake_ctx = SharedMarketContext(
        symbol="EURUSD", mt5_symbol="EURUSD.r", timeframe="H1",
        candles=[], indicators={}, current_price=1.1,
        signal=fake_signal, llm_result=None, news_signal=None,
    )
    # Primary returns result with shared_ctx populated
    fake_primary_result = AnalysisResult(
        signal=fake_signal, order_placed=False, ticket=None, journal_id=1,
        shared_ctx=fake_ctx,
    )

    # Only account 101 is clear; 102 is blocked
    clear = [(101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None})]
    blocked = [(102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None})]

    mock_db = AsyncMock()
    MockSession = MagicMock()
    MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("services.scheduler._preflight_risk_check", new_callable=AsyncMock,
               return_value=(clear, blocked)), \
         patch("services.scheduler.AsyncSessionLocal", MockSession), \
         patch("services.ai_trading.AITradingService.analyze_and_trade",
               new_callable=AsyncMock, return_value=fake_primary_result) as mock_analyze:

        await sched_module._run_group_strategy_job(
            strategy_id=10, symbol="EURUSD", timeframe="H1",
            module_path=None, class_name=None,
        )

    # Called once for primary account 101; 102 is blocked so no secondary call
    assert mock_analyze.await_count == 1
    del sched_module._group_accounts[job_id]


@pytest.mark.asyncio
async def test_run_group_strategy_job_calls_llm_once_executes_twice():
    """Group job: AITradingService called for primary (full pipeline) + secondary (shared_ctx)."""
    import services.scheduler as sched_module

    job_id = "strat_10_EURUSD"
    sched_module._group_accounts[job_id] = [
        (101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
        (102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
    ]

    from ai.orchestrator import TradingSignal
    from services.ai_trading import SharedMarketContext, AnalysisResult

    fake_signal = TradingSignal(action="HOLD", entry=0.0, stop_loss=0.0, take_profit=0.0,
                                confidence=0.5, rationale="test", timeframe="H1")
    fake_ctx = SharedMarketContext(
        symbol="EURUSD", mt5_symbol="EURUSD.r", timeframe="H1",
        candles=[], indicators={}, current_price=1.1,
        signal=fake_signal, llm_result=None, news_signal=None,
    )
    fake_primary_result = AnalysisResult(
        signal=fake_signal, order_placed=False, ticket=None, journal_id=1,
        shared_ctx=fake_ctx,
    )
    fake_secondary_result = AnalysisResult(
        signal=fake_signal, order_placed=False, ticket=None, journal_id=2,
        shared_ctx=None,
    )

    clear = [
        (101, {"lot_size": 0.1, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
        (102, {"lot_size": 0.05, "sl_pips": 20.0, "tp_pips": 40.0, "news_filter": True, "custom_prompt": None}),
    ]

    mock_db = AsyncMock()
    MockSession = MagicMock()
    MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    MockSession.return_value.__aexit__ = AsyncMock(return_value=False)

    # First call (primary) returns shared_ctx, second call (secondary) returns no shared_ctx
    mock_analyze = AsyncMock(side_effect=[fake_primary_result, fake_secondary_result])

    with patch("services.scheduler._preflight_risk_check", new_callable=AsyncMock,
               return_value=(clear, [])), \
         patch("services.scheduler.AsyncSessionLocal", MockSession), \
         patch("services.ai_trading.AITradingService.analyze_and_trade", mock_analyze):

        await sched_module._run_group_strategy_job(
            strategy_id=10, symbol="EURUSD", timeframe="H1",
            module_path=None, class_name=None,
        )

    # Primary (account 101) + secondary (account 102) = 2 total calls
    assert mock_analyze.await_count == 2

    # Primary call: no shared_ctx
    primary_call_kwargs = mock_analyze.call_args_list[0].kwargs
    assert primary_call_kwargs.get("shared_ctx") is None
    assert primary_call_kwargs["account_id"] == 101

    # Secondary call: receives shared_ctx
    secondary_call_kwargs = mock_analyze.call_args_list[1].kwargs
    assert secondary_call_kwargs.get("shared_ctx") is fake_ctx
    assert secondary_call_kwargs["account_id"] == 102

    del sched_module._group_accounts[job_id]
