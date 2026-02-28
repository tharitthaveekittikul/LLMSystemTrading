import json
import pytest
from db.models import Strategy, AccountStrategy, Trade, AIJournal


def test_strategy_defaults():
    s = Strategy(name="Test", symbols=json.dumps(["EURUSD"]))
    assert s.strategy_type == "config"
    assert s.trigger_type == "candle_close"
    assert s.is_active is True
    assert s.news_filter is True


def test_account_strategy_unique_constraint():
    unique_cols = [
        set(c.columns.keys())
        for c in AccountStrategy.__table__.constraints
        if hasattr(c, "columns") and len(list(c.columns)) == 2
    ]
    assert {"account_id", "strategy_id"} in unique_cols


def test_trade_has_strategy_id_column():
    cols = {c.name for c in Trade.__table__.columns}
    assert "strategy_id" in cols


def test_journal_has_strategy_id_column():
    cols = {c.name for c in AIJournal.__table__.columns}
    assert "strategy_id" in cols


def test_trade_strategy_relationship_defined():
    assert hasattr(Trade, "strategy")


def test_journal_strategy_relationship_defined():
    assert hasattr(AIJournal, "strategy")
