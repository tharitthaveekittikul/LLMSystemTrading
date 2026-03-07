import pytest
from services.backtest_analytics import aggregate_by_group, build_heatmap, generate_recommendations


def _make_trades(specs: list[tuple]) -> list[dict]:
    """specs = list of (symbol, pattern_name, profit)"""
    trades = []
    for symbol, pattern, profit in specs:
        trades.append({
            "symbol": symbol,
            "pattern_name": pattern,
            "profit": profit,
            "direction": "BUY",
        })
    return trades


def test_aggregate_by_group_basic():
    trades = _make_trades([
        ("EURUSD", "Gartley", 100),
        ("EURUSD", "Gartley", -50),
        ("XAUUSD", "Bat", 200),
    ])
    groups = aggregate_by_group(trades, group_by="pattern_name")
    names = [g["name"] for g in groups]
    assert "Gartley" in names
    assert "Bat" in names
    gartley = next(g for g in groups if g["name"] == "Gartley")
    assert gartley["trades"] == 2
    assert abs(gartley["total_pnl"] - 50.0) < 0.01
    assert abs(gartley["win_rate"] - 0.5) < 0.01


def test_build_heatmap_shape():
    trades = _make_trades([
        ("EURUSD", "Gartley", 100), ("GBPJPY", "Gartley", -30),
        ("EURUSD", "Bat", 50),
    ])
    heatmap = build_heatmap(trades, axis1="symbol", axis2="pattern_name", metric="win_rate")
    assert "labels_x" in heatmap
    assert "labels_y" in heatmap
    assert "values" in heatmap
    assert len(heatmap["labels_x"]) == len(heatmap["values"])


def test_generate_recommendations_returns_strings():
    trades = _make_trades([
        ("EURUSD", "Bat", 300), ("EURUSD", "Bat", 200),
        ("GBPJPY", "Crab", -100), ("GBPJPY", "Crab", -200),
    ])
    heatmap = build_heatmap(trades, "symbol", "pattern_name", "win_rate")
    recs = generate_recommendations(heatmap, trades)
    assert isinstance(recs, list)
    assert all(isinstance(r, str) for r in recs)
    assert len(recs) >= 1
