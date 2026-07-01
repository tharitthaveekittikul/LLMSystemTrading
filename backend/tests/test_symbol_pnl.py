"""Tests for plan 06: LLM cost + P&L attribution, grouped by symbol or source.

_aggregate_symbol_pnl is pure Python (no DB), so these exercise it directly
with synthetic joined rows shaped like what _fetch_symbol_pnl_rows returns —
one row per (trade, llm_call) pair, with cost_usd=None for trades that never
matched an llm_calls row (manual trades, or an AI trade with no cost rows yet).
"""
from types import SimpleNamespace

from api.routes.llm_analytics._performance import _aggregate_symbol_pnl


def _row(trade_id, symbol, source, profit, cost_usd):
    return SimpleNamespace(
        trade_id=trade_id, symbol=symbol, source=source, profit=profit, cost_usd=cost_usd,
    )


def test_dedups_profit_but_sums_cost_across_multiple_llm_calls():
    """One AI trade with 3 llm_calls rows (e.g. entry + 2 maintenance reviews) —
    profit must be counted once, cost summed across all 3."""
    rows = [
        _row(1, "EURUSD", "ai", 100.0, 0.001),
        _row(1, "EURUSD", "ai", 100.0, 0.002),  # same trade, same profit, different call
        _row(1, "EURUSD", "ai", 100.0, 0.0015),
    ]
    result = _aggregate_symbol_pnl(rows, group_by="symbol")
    assert len(result) == 1
    r = result[0]
    assert r.trade_count == 1
    assert r.realized_pnl_usd == 100.0
    assert r.attributed_llm_cost_usd == round(0.001 + 0.002 + 0.0015, 8)
    assert r.net_pnl_usd == round(100.0 - (0.001 + 0.002 + 0.0015), 6)


def test_manual_trade_excluded_from_cost_and_realized_pnl():
    """A manual trade (no pipeline_run, cost_usd=None via outer join) must be
    tracked separately and never netted against LLM cost."""
    rows = [
        _row(1, "EURUSD", "ai", 50.0, 0.001),
        _row(2, "EURUSD", "manual", -20.0, None),
    ]
    result = _aggregate_symbol_pnl(rows, group_by="symbol")
    assert len(result) == 1
    r = result[0]
    assert r.trade_count == 2
    assert r.realized_pnl_usd == 50.0          # manual trade's -20 excluded
    assert r.attributed_llm_cost_usd == 0.001
    assert r.manual_trade_count == 1
    assert r.manual_pnl_usd == -20.0


def test_groups_by_symbol():
    rows = [
        _row(1, "EURUSD", "ai", 100.0, 0.001),
        _row(2, "XAUUSD", "ai", -30.0, 0.002),
    ]
    result = _aggregate_symbol_pnl(rows, group_by="symbol")
    groups = {r.group: r for r in result}
    assert set(groups) == {"EURUSD", "XAUUSD"}
    assert groups["EURUSD"].net_pnl_usd == round(100.0 - 0.001, 6)
    assert groups["XAUUSD"].net_pnl_usd == round(-30.0 - 0.002, 6)


def test_groups_by_source_strategy():
    rows = [
        _row(1, "EURUSD", "HarmonicStrategy", 100.0, 0.001),
        _row(2, "XAUUSD", "HarmonicStrategy", 40.0, 0.001),
        _row(3, "EURUSD", "ai", -10.0, 0.0005),
    ]
    result = _aggregate_symbol_pnl(rows, group_by="source")
    groups = {r.group: r for r in result}
    assert set(groups) == {"HarmonicStrategy", "ai"}
    assert groups["HarmonicStrategy"].trade_count == 2
    assert groups["HarmonicStrategy"].realized_pnl_usd == 140.0


def test_sorted_by_net_pnl_descending():
    rows = [
        _row(1, "EURUSD", "ai", -50.0, 0.001),
        _row(2, "XAUUSD", "ai", 200.0, 0.001),
    ]
    result = _aggregate_symbol_pnl(rows, group_by="symbol")
    assert [r.group for r in result] == ["XAUUSD", "EURUSD"]


def test_empty_rows_returns_empty_list():
    assert _aggregate_symbol_pnl([], group_by="symbol") == []
