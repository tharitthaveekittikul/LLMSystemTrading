from services.risk_manager import exceeds_position_limit, exceeds_drawdown_limit


def test_position_limit_not_exceeded():
    positions = [{"ticket": 1}, {"ticket": 2}]
    exceeded, reason = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is False
    assert reason == ""


def test_position_limit_exactly_at_max():
    positions = [{"ticket": i} for i in range(5)]
    exceeded, reason = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is True
    assert "5/5" in reason


def test_position_limit_exceeded():
    positions = [{"ticket": i} for i in range(6)]
    exceeded, _ = exceeds_position_limit(positions, max_positions=5)
    assert exceeded is True


def test_drawdown_not_exceeded():
    exceeded, reason = exceeds_drawdown_limit(equity=9500.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is False
    assert reason == ""


def test_drawdown_exactly_at_limit():
    # 10000 - 9000 = 1000 loss = 10% drawdown
    exceeded, reason = exceeds_drawdown_limit(equity=9000.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is True
    assert "10.00%" in reason


def test_drawdown_exceeded():
    exceeded, _ = exceeds_drawdown_limit(equity=8000.0, balance=10000.0, max_drawdown_pct=10.0)
    assert exceeded is True


def test_drawdown_zero_balance_safe():
    # Guard against division by zero
    exceeded, _ = exceeds_drawdown_limit(equity=0.0, balance=0.0, max_drawdown_pct=10.0)
    assert exceeded is False
