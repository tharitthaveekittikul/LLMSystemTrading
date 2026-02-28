"""Tests for HistoryService."""
import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_deal(ticket, position_id, entry, deal_type, symbol="EURUSD",
               volume=0.1, price=1.0850, profit=0.0, commission=0.0,
               swap=0.0, ts=1700000000):
    return {
        "ticket": ticket, "position_id": position_id, "entry": entry,
        "type": deal_type, "symbol": symbol, "volume": volume,
        "price": price, "profit": profit, "commission": commission,
        "swap": swap, "time": ts,
    }


# ── get_performance_summary ────────────────────────────────────────────────

def test_performance_summary_empty():
    from services.history_sync import HistoryService
    s = HistoryService.get_performance_summary([])
    assert s["trade_count"] == 0
    assert s["win_rate"] == 0.0
    assert s["total_pnl"] == 0.0


def test_performance_summary_two_wins_one_loss():
    from services.history_sync import HistoryService
    deals = [
        _make_deal(1, 100, 1, 1, profit=30.0),   # OUT, win
        _make_deal(2, 101, 1, 0, profit=-10.0),  # OUT, loss
        _make_deal(3, 102, 1, 1, profit=20.0),   # OUT, win
        _make_deal(4, 100, 0, 0),                # IN deal — excluded
    ]
    s = HistoryService.get_performance_summary(deals)
    assert s["trade_count"] == 3
    assert s["winning_trades"] == 2
    assert abs(s["win_rate"] - 2/3) < 0.001
    assert abs(s["total_pnl"] - 40.0) < 0.01


def test_performance_summary_profit_factor():
    from services.history_sync import HistoryService
    deals = [
        _make_deal(1, 100, 1, 1, profit=60.0),
        _make_deal(2, 101, 1, 0, profit=-20.0),
    ]
    s = HistoryService.get_performance_summary(deals)
    # profit_factor = gross_profit / abs(gross_loss) = 60 / 20 = 3.0
    assert abs(s["profit_factor"] - 3.0) < 0.01


def test_performance_summary_no_losses_profit_factor_is_inf():
    from services.history_sync import HistoryService
    deals = [_make_deal(1, 100, 1, 1, profit=30.0)]
    s = HistoryService.get_performance_summary(deals)
    import math
    assert math.isinf(s["profit_factor"])


def test_performance_summary_includes_inout_deals():
    """DEAL_ENTRY_INOUT (entry=2) deals must be counted in performance stats."""
    from services.history_sync import HistoryService
    deals = [
        _make_deal(1, 100, 1, 1, profit=30.0),   # OUT
        _make_deal(2, 101, 2, 1, profit=20.0),   # INOUT — should be counted
        _make_deal(3, 102, 0, 0),                 # IN — excluded
    ]
    s = HistoryService.get_performance_summary(deals)
    assert s["trade_count"] == 2
    assert s["total_pnl"] == 50.0


# ── format_for_llm ─────────────────────────────────────────────────────────

def test_format_for_llm_empty():
    from services.history_sync import HistoryService
    result = HistoryService.format_for_llm([], {})
    assert result == ""


def test_format_for_llm_includes_symbol_direction_profit():
    from services.history_sync import HistoryService
    out_deals = [_make_deal(1, 100, 1, 0, symbol="EURUSD", profit=30.0)]
    in_deals_by_pos = {100: _make_deal(10, 100, 0, 0, price=1.0820)}
    result = HistoryService.format_for_llm(out_deals, in_deals_by_pos, limit=5)
    assert "EURUSD" in result
    assert "BUY" in result  # type=0 on IN deal means BUY direction
    assert "30.0" in result or "+30" in result


def test_format_for_llm_respects_limit():
    from services.history_sync import HistoryService
    out_deals = [_make_deal(i, i+100, 1, 1, profit=10.0) for i in range(10)]
    result = HistoryService.format_for_llm(out_deals, {}, limit=3)
    # Only last 3 should appear
    lines = [l for l in result.splitlines() if l.strip().startswith("-")]
    assert len(lines) == 3


# ── _pair_deals ────────────────────────────────────────────────────────────

def test_pair_deals_separates_in_and_out():
    from services.history_sync import HistoryService
    deals = [
        _make_deal(1, 100, 0, 0),   # IN
        _make_deal(2, 100, 1, 1),   # OUT
        _make_deal(3, 101, 0, 0),   # IN (unmatched, no OUT)
    ]
    out_deals, in_by_pos = HistoryService._pair_deals(deals)
    assert len(out_deals) == 1
    assert out_deals[0]["ticket"] == 2
    assert 100 in in_by_pos
    assert 101 in in_by_pos


def test_pair_deals_treats_inout_as_out():
    """entry=2 (DEAL_ENTRY_INOUT) must be treated as an OUT deal."""
    from services.history_sync import HistoryService
    deals = [
        _make_deal(1, 100, 0, 0),   # IN
        _make_deal(2, 100, 2, 1),   # INOUT — should be treated as OUT
    ]
    out_deals, in_by_pos = HistoryService._pair_deals(deals)
    assert len(out_deals) == 1
    assert out_deals[0]["ticket"] == 2
    assert 100 in in_by_pos


# ── sync_to_db ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_to_db_imports_new_trade():
    from services.history_sync import HistoryService

    deals = [
        _make_deal(10, 200, 0, 0, price=1.0820, ts=1700000000),  # IN BUY
        _make_deal(11, 200, 1, 1, price=1.0850, profit=30.0,
                   commission=-2.0, swap=-0.5, ts=1700003600),    # OUT
    ]

    mock_account = MagicMock(
        id=1, login=12345, password_encrypted="enc",
        server="srv", mt5_path="", paper_trade_enabled=False,
    )
    mock_db = AsyncMock()
    # Simulate no existing trade with ticket=200
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with patch("services.history_sync.MT5Bridge") as mock_bridge_cls, \
         patch("services.history_sync.decrypt", return_value="pw"), \
         patch("services.history_sync.settings"):
        mock_bridge = AsyncMock()
        mock_bridge.history_deals_get.return_value = deals
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        svc = HistoryService()
        result = await svc.sync_to_db(mock_account, days=90, db=mock_db)

    assert result["imported"] == 1
    assert result["total_fetched"] == 2
    mock_db.add.assert_called_once()
    trade_added = mock_db.add.call_args[0][0]
    from db.models import Trade
    assert isinstance(trade_added, Trade)
    assert trade_added.ticket == 200
    assert trade_added.direction == "BUY"
    assert abs(trade_added.entry_price - 1.0820) < 0.0001
    assert abs(trade_added.close_price - 1.0850) < 0.0001
    assert abs(trade_added.profit - (30.0 - 2.0 - 0.5)) < 0.01
    assert trade_added.source == "manual"


@pytest.mark.asyncio
async def test_sync_to_db_skips_existing_ticket():
    from services.history_sync import HistoryService

    deals = [
        _make_deal(10, 200, 0, 0, ts=1700000000),
        _make_deal(11, 200, 1, 1, profit=30.0, ts=1700003600),
    ]

    mock_account = MagicMock(id=1, login=12345, password_encrypted="enc", server="srv", mt5_path="")
    mock_db = AsyncMock()
    # Simulate existing trade with ticket=200
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MagicMock()  # found
    mock_db.execute.return_value = mock_result

    with patch("services.history_sync.MT5Bridge") as mock_bridge_cls, \
         patch("services.history_sync.decrypt", return_value="pw"), \
         patch("services.history_sync.settings"):
        mock_bridge = AsyncMock()
        mock_bridge.history_deals_get.return_value = deals
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        svc = HistoryService()
        result = await svc.sync_to_db(mock_account, days=90, db=mock_db)

    assert result["imported"] == 0
    mock_db.add.assert_not_called()
