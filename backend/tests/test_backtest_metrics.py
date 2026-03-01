import pytest
from services.backtest_metrics import compute_metrics, compute_monthly_pnl


def _make_trades(profits: list[float]) -> list[dict]:
    return [{"profit": p, "equity_after": 0.0} for p in profits]


def test_empty_returns_zeros():
    m = compute_metrics([], initial_balance=10_000.0)
    assert m["total_trades"] == 0
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0


def test_all_wins():
    trades = _make_trades([100.0, 200.0, 50.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    assert m["total_trades"] == 3
    assert m["win_rate"] == 1.0
    assert m["profit_factor"] == 9999.0  # inf capped


def test_profit_factor():
    trades = _make_trades([100.0, -50.0, 200.0, -100.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    # gross_profit=300, gross_loss=150 → 2.0
    assert m["profit_factor"] == pytest.approx(2.0, rel=1e-3)


def test_max_drawdown():
    # equity: 10000→10100→10200→10050→10150; peak=10200 trough=10050 → dd=150
    trades = _make_trades([100.0, 100.0, -150.0, 100.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    # max_drawdown_pct = 150 / 10000 * 100 = 1.5%
    assert m["max_drawdown_pct"] == pytest.approx(1.5, rel=1e-2)


def test_expectancy():
    # 2 wins avg 100, 1 loss avg -50 → (0.667*100) + (0.333*(-50)) ≈ 50
    trades = _make_trades([100.0, 100.0, -50.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    assert m["expectancy"] == pytest.approx(50.0, rel=1e-2)


def test_max_consecutive():
    trades = _make_trades([10, 10, -5, 10, 10, 10, -5, -5])
    m = compute_metrics(trades, initial_balance=10_000.0)
    assert m["max_consec_wins"] == 3
    assert m["max_consec_losses"] == 2


def test_total_return_pct():
    trades = _make_trades([500.0, -200.0])
    m = compute_metrics(trades, initial_balance=10_000.0)
    # total_return = 300, pct = 300/10000*100 = 3.0
    assert m["total_return_pct"] == pytest.approx(3.0, rel=1e-3)


def test_compute_monthly_pnl():
    from datetime import datetime, timezone
    trades = [
        {"profit": 100.0, "exit_time": datetime(2020, 1, 15, tzinfo=timezone.utc)},
        {"profit": -50.0, "exit_time": datetime(2020, 1, 20, tzinfo=timezone.utc)},
        {"profit": 200.0, "exit_time": datetime(2020, 2, 5, tzinfo=timezone.utc)},
    ]
    result = compute_monthly_pnl(trades)
    assert len(result) == 2
    assert result[0]["year"] == 2020
    assert result[0]["month"] == 1
    assert result[0]["pnl"] == pytest.approx(50.0)
    assert result[0]["trade_count"] == 2
    assert result[1]["month"] == 2
    assert result[1]["pnl"] == pytest.approx(200.0)
