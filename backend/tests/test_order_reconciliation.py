"""Tests for plan 01 (pending-order sync + manual/AI trade tagging), Part B.

Covers the reconciliation paths in api/routes/accounts/_sync.py
(sync_orders / sync_account) using a mocked MT5Bridge: filled-pending
detection, closed-position detection (which must trigger the same
research-loop path _sync.py already uses), cancelled-pending detection,
and manual-position/trade backfill triggering the positions_update broadcast.

Also verifies (plan 01 acceptance criterion) that check_position_limit /
check_hedging already correctly account for manually-opened MT5 exposure,
and that check_rate_limit sees trades backfilled with source="manual".
"""
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Trade


def _mock_account(account_id: int = 7) -> MagicMock:
    return MagicMock(
        id=account_id, name="Test", is_active=True, login=1,
        password_encrypted="enc", server="srv", mt5_path="",
    )


def _mock_db(open_trades: list[Trade]) -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=_mock_account())
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = open_trades
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    return mock_db


def _mock_position(ticket: int, symbol: str = "EURUSD") -> dict:
    return {
        "ticket": ticket, "symbol": symbol, "type": 0, "volume": 0.1,
        "price_open": 1.1000, "price_current": 1.1010, "sl": 1.0950,
        "tp": 1.1050, "profit": 1.0, "swap": 0.0, "time": 1700000000,
    }


async def _drain_background_tasks() -> None:
    """Await any asyncio.ensure_future() fire-and-forget tasks _sync.py scheduled
    (post-trade analysis / research-loop trigger) so assertions can run after."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# ── sync_orders: filled / closed / cancelled detection ─────────────────────

@pytest.mark.asyncio
async def test_sync_orders_detects_filled_pending_order():
    """Pending order gone from MT5's order list, ticket now a live position
    → order_status upgraded to 'filled', closed_at stays None."""
    from api.routes.accounts._sync import sync_orders

    trade = Trade(
        id=1, account_id=7, ticket=500, symbol="EURUSD", direction="BUY",
        volume=0.1, entry_price=1.1000, stop_loss=1.0950, take_profit=1.1050,
        opened_at=datetime.now(UTC), order_status="pending", order_type="limit",
        source="ai",
    )
    mock_db = _mock_db([trade])

    with patch("api.routes.accounts._sync.decrypt", return_value="pw"), \
         patch("api.routes.accounts._sync.MT5Bridge") as mock_bridge_cls, \
         patch("api.routes.accounts._sync._broadcast_positions_update", new=AsyncMock()) as broadcast_mock:
        mock_bridge = AsyncMock()
        mock_bridge.get_positions.return_value = [_mock_position(500)]
        mock_bridge.get_orders.return_value = []
        mock_bridge.history_orders_get.return_value = [
            {"ticket": 500, "position_id": 500, "state": 4},  # ORDER_STATE_FILLED
        ]
        mock_bridge.history_deals_get.return_value = []
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        await sync_orders(account_id=7, db=mock_db)
        await _drain_background_tasks()

    assert trade.order_status == "filled"
    assert trade.closed_at is None
    mock_db.commit.assert_called_once()
    broadcast_mock.assert_called_once()


@pytest.mark.asyncio
async def test_sync_orders_detects_closed_position_and_triggers_research_loop():
    """Open position gone from MT5, matched to a closing deal in history
    → order_status='filled' stays but closed_at/profit set, and the SAME
    research-loop trigger (services.research_loop.maybe_run) _sync.py already
    uses for dashboard-triggered closes must fire — not a duplicate path."""
    from api.routes.accounts._sync import sync_orders

    trade = Trade(
        id=2, account_id=7, ticket=600, symbol="EURUSD", direction="BUY",
        volume=0.1, entry_price=1.1000, stop_loss=1.0950, take_profit=1.1050,
        opened_at=datetime.now(UTC), order_status="filled", order_type="market",
        source="ai",
    )
    mock_db = _mock_db([trade])

    closing_deal = {
        "position_id": 600, "entry": 1, "price": 1.1030,
        "profit": 30.0, "time": 1700003600,
    }

    with patch("api.routes.accounts._sync.decrypt", return_value="pw"), \
         patch("api.routes.accounts._sync.MT5Bridge") as mock_bridge_cls, \
         patch("api.routes.accounts._sync._broadcast_positions_update", new=AsyncMock()), \
         patch("services.research_loop.maybe_run", new=AsyncMock()) as maybe_run_mock, \
         patch("services.trade_analyzer.analyze_closed_trade", new=AsyncMock()):
        mock_bridge = AsyncMock()
        mock_bridge.get_positions.return_value = []  # position no longer open
        mock_bridge.get_orders.return_value = []
        mock_bridge.history_orders_get.return_value = [{"ticket": 600, "position_id": 600}]
        mock_bridge.history_deals_get.return_value = [closing_deal]
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        await sync_orders(account_id=7, db=mock_db)
        await _drain_background_tasks()

    assert trade.order_status == "filled"
    assert trade.closed_at is not None
    assert trade.profit == 30.0
    assert trade.close_price == 1.1030
    maybe_run_mock.assert_called_once()
    assert maybe_run_mock.call_args[0][0] == 7  # account_id
    assert maybe_run_mock.call_args[0][2] == 1  # n_closed


@pytest.mark.asyncio
async def test_sync_orders_detects_cancelled_pending_order():
    """Pending order gone from MT5 with no history record at all (broker
    silently dropped it, or it expired without a discoverable state)
    → order_status = 'cancelled'."""
    from api.routes.accounts._sync import sync_orders

    trade = Trade(
        id=3, account_id=7, ticket=700, symbol="EURUSD", direction="SELL",
        volume=0.1, entry_price=1.1000, stop_loss=1.1050, take_profit=1.0950,
        opened_at=datetime.now(UTC), order_status="pending", order_type="limit",
        source="ai",
    )
    mock_db = _mock_db([trade])

    with patch("api.routes.accounts._sync.decrypt", return_value="pw"), \
         patch("api.routes.accounts._sync.MT5Bridge") as mock_bridge_cls, \
         patch("api.routes.accounts._sync._broadcast_positions_update", new=AsyncMock()) as broadcast_mock:
        mock_bridge = AsyncMock()
        mock_bridge.get_positions.return_value = []
        mock_bridge.get_orders.return_value = []
        mock_bridge.history_orders_get.return_value = []
        mock_bridge.history_deals_get.return_value = []
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        await sync_orders(account_id=7, db=mock_db)

    assert trade.order_status == "cancelled"
    assert trade.closed_at is not None
    broadcast_mock.assert_called_once()


@pytest.mark.asyncio
async def test_sync_orders_no_state_change_does_not_broadcast():
    """Nothing changed in MT5 → no WS broadcast (avoid noisy no-op pushes)."""
    from api.routes.accounts._sync import sync_orders

    trade = Trade(
        id=4, account_id=7, ticket=800, symbol="EURUSD", direction="BUY",
        volume=0.1, entry_price=1.1000, stop_loss=1.0950, take_profit=1.1050,
        opened_at=datetime.now(UTC), order_status="filled", order_type="market",
        source="ai",
    )
    mock_db = _mock_db([trade])

    with patch("api.routes.accounts._sync.decrypt", return_value="pw"), \
         patch("api.routes.accounts._sync.MT5Bridge") as mock_bridge_cls, \
         patch("api.routes.accounts._sync._broadcast_positions_update", new=AsyncMock()) as broadcast_mock:
        mock_bridge = AsyncMock()
        mock_bridge.get_positions.return_value = [_mock_position(800)]  # still open
        mock_bridge.get_orders.return_value = []
        mock_bridge.history_orders_get.return_value = []
        mock_bridge.history_deals_get.return_value = []
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        await sync_orders(account_id=7, db=mock_db)

    assert trade.order_status == "filled"
    assert trade.closed_at is None
    broadcast_mock.assert_not_called()


# ── sync_account: manual-position/trade backfill ───────────────────────────

@pytest.mark.asyncio
async def test_sync_account_manual_backfill_triggers_broadcast():
    """An MT5 deal with no matching trades row (a manually-placed trade —
    see services/history_sync.py's existing source="manual" insertion,
    covered by tests/test_history_sync.py) surfaces via sync_account's
    Phase 2 backfill and must trigger the positions_update broadcast so the
    dashboard picks it up without a refresh."""
    from api.routes.accounts._sync import sync_account

    mock_db = _mock_db([])  # no open DB trades

    with patch("api.routes.accounts._sync.decrypt", return_value="pw"), \
         patch("api.routes.accounts._sync.MT5Bridge") as mock_bridge_cls, \
         patch("api.routes.accounts._sync.HistoryService") as mock_hs_cls, \
         patch("api.routes.accounts._sync._broadcast_positions_update", new=AsyncMock()) as broadcast_mock:
        mock_bridge = AsyncMock()
        mock_bridge.get_positions.return_value = []
        mock_bridge.get_orders.return_value = []
        mock_bridge.history_orders_get.return_value = []
        mock_bridge.history_deals_get.return_value = []
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        mock_hs = AsyncMock()
        mock_hs.sync_deals_to_db = AsyncMock(return_value={
            "imported": 1, "updated": 0, "total_fetched": 1, "new_trade_ids": [999],
        })
        mock_hs_cls.return_value = mock_hs

        await sync_account(account_id=7, db=mock_db)
        await _drain_background_tasks()

    broadcast_mock.assert_called_once()


@pytest.mark.asyncio
async def test_sync_account_no_changes_does_not_broadcast():
    from api.routes.accounts._sync import sync_account

    mock_db = _mock_db([])

    with patch("api.routes.accounts._sync.decrypt", return_value="pw"), \
         patch("api.routes.accounts._sync.MT5Bridge") as mock_bridge_cls, \
         patch("api.routes.accounts._sync.HistoryService") as mock_hs_cls, \
         patch("api.routes.accounts._sync._broadcast_positions_update", new=AsyncMock()) as broadcast_mock:
        mock_bridge = AsyncMock()
        mock_bridge.get_positions.return_value = []
        mock_bridge.get_orders.return_value = []
        mock_bridge.history_orders_get.return_value = []
        mock_bridge.history_deals_get.return_value = []
        mock_bridge_cls.return_value.__aenter__.return_value = mock_bridge

        mock_hs = AsyncMock()
        mock_hs.sync_deals_to_db = AsyncMock(return_value={
            "imported": 0, "updated": 0, "total_fetched": 0, "new_trade_ids": [],
        })
        mock_hs_cls.return_value = mock_hs

        await sync_account(account_id=7, db=mock_db)

    broadcast_mock.assert_not_called()


# ── check_position_limit / check_hedging already see manual exposure ──────

def test_check_position_limit_counts_manually_opened_positions():
    """check_position_limit/check_hedging read the LIVE MT5 positions list
    passed in by the caller — not the `trades` DB table — so a manually
    opened position (no matching `trades` row, no `source` concept at the
    MT5 API level at all) is already counted correctly today, with no
    reconciliation step required for risk-check correctness. Reconciliation
    (Part B) is about dashboard visibility, not risk-check correctness —
    verified here rather than assumed, per plan 01's acceptance criteria."""
    from services.risk_manager import RiskConfig, check_hedging, check_position_limit

    manual_position = {"ticket": 9001, "symbol": "EURUSD", "type": 0}  # BUY

    cfg = RiskConfig(position_limit_enabled=True, max_open_positions=1)
    exceeded, reason = check_position_limit([manual_position], cfg)
    assert exceeded is True
    assert "1/1" in reason

    cfg_hedge = RiskConfig(hedging_allowed=False)
    exceeded2, reason2 = check_hedging("EURUSD", "SELL", [manual_position], cfg_hedge)
    assert exceeded2 is True
    assert "9001" in reason2


@pytest.mark.asyncio
async def test_check_rate_limit_counts_manually_backfilled_trade():
    """A manual MT5 trade backfilled into `trades` (source="manual", via
    history_sync.sync_deals_to_db — see test_history_sync.py) DOES count
    toward check_rate_limit's rolling per-symbol window, since
    check_rate_limit filters only on symbol + opened_at, not on `source`.
    This is a pre-existing behavior (not introduced by this change) —
    documented with a real DB round trip rather than assumed either way."""
    from sqlalchemy import delete

    from db.models import Account
    from db.postgres import AsyncSessionLocal
    from services.risk_manager import RiskConfig, check_rate_limit

    async with AsyncSessionLocal() as db:
        account = Account(
            name="Reconciliation Rate Limit Test", broker="TestBroker",
            login=999999002, password_encrypted="x", server="srv", is_active=True,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)

        trade = Trade(
            account_id=account.id, ticket=123456, symbol="EURUSD", direction="BUY",
            volume=0.1, entry_price=1.1, stop_loss=1.09, take_profit=1.11,
            opened_at=datetime.now(UTC), source="manual", order_status="filled",
        )
        db.add(trade)
        await db.commit()

        cfg = RiskConfig(rate_limit_enabled=True, rate_limit_max_trades=1, rate_limit_window_hours=4.0)
        exceeded, reason = await check_rate_limit("EURUSD", cfg, db)

        await db.execute(delete(Trade).where(Trade.account_id == account.id))
        await db.execute(delete(Account).where(Account.id == account.id))
        await db.commit()

    assert exceeded is True
    assert "EURUSD" in reason
