# MT5 History & Per-Account Terminal Path — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-account `mt5_path` to support multiple MT5 terminals, add `history_deals_get` / `history_orders_get` to `MT5Bridge`, create `HistoryService` for sync/analytics/AI context, and expose two new API endpoints.

**Architecture:** `MT5Bridge` gains two thin I/O methods. `services/history_sync.py` owns all business logic (group deals into trades, upsert, compute stats, format for LLM). `accounts.py` routes call the service and expose two endpoints. `analyze_and_trade` in `ai_trading.py` injects recent trade history as extra LLM context.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, MetaTrader5, pytest + unittest.mock

---

## Context

- Alembic is already initialized. Latest migration: `53e6a27575ae` (add_strategy_engine). New migration chains from this.
- `path=settings.mt5_path` appears in **5 places** across `accounts.py` (lines 134, 200) and `ai_trading.py` (lines 112, 151, 286). All must use `account.mt5_path or settings.mt5_path`.
- Run tests from `backend/` dir: `uv run pytest -v`
- Run migrations from `backend/` dir: `uv run alembic upgrade head`

---

## Task 1: `Account.mt5_path` — Model + Migration

**Files:**
- Modify: `backend/db/models.py`
- Create: `backend/alembic/versions/xxxx_add_mt5_path_to_accounts.py` (auto-generated name)

### Step 1: Add column to the model

In `db/models.py`, inside class `Account`, after the `paper_trade_enabled` line (line 26), add:

```python
mt5_path: Mapped[str] = mapped_column(String(500), default="")
```

### Step 2: Generate the Alembic migration

```bash
cd backend
uv run alembic revision --autogenerate -m "add_mt5_path_to_accounts"
```

Expected: creates `alembic/versions/<hash>_add_mt5_path_to_accounts.py`

### Step 3: Inspect and verify the generated migration

Open the generated file. The `upgrade()` must contain exactly:

```python
op.add_column('accounts', sa.Column('mt5_path', sa.String(length=500), nullable=False, server_default=''))
```

If autogenerate produced something different, correct it manually.

### Step 4: Apply the migration

```bash
uv run alembic upgrade head
```

Expected output ends with: `Running upgrade 53e6a27575ae -> <new_hash>, add_mt5_path_to_accounts`

### Step 5: Verify column exists

```bash
uv run python -c "
import asyncio
from sqlalchemy import text
from db.postgres import engine

async def check():
    async with engine.connect() as conn:
        r = await conn.execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='accounts' AND column_name='mt5_path'\"))
        print(r.fetchone())

asyncio.run(check())
"
```

Expected: `('mt5_path',)`

---

## Task 2: Update Account Schemas and All `AccountCredentials` Construction

**Files:**
- Modify: `backend/api/routes/accounts.py`
- Modify: `backend/services/ai_trading.py`
- Create: `backend/tests/test_account_mt5_path.py`

### Step 1: Write failing tests

Create `backend/tests/test_account_mt5_path.py`:

```python
"""Tests for mt5_path field on Account schema and credential construction."""
import pytest
from pydantic import ValidationError


def test_account_create_accepts_mt5_path():
    from api.routes.accounts import AccountCreate
    a = AccountCreate(
        name="Test", broker="ICM", login=12345,
        password="pw", server="srv", mt5_path="C:/MT5_Account1"
    )
    assert a.mt5_path == "C:/MT5_Account1"


def test_account_create_mt5_path_defaults_empty():
    from api.routes.accounts import AccountCreate
    a = AccountCreate(name="Test", broker="ICM", login=12345, password="pw", server="srv")
    assert a.mt5_path == ""


def test_account_response_includes_mt5_path():
    from api.routes.accounts import AccountResponse
    import datetime
    r = AccountResponse(
        id=1, name="Test", broker="ICM", login=12345,
        server="srv", is_live=False, is_active=True,
        allowed_symbols=[], max_lot_size=0.1,
        auto_trade_enabled=True, mt5_path="C:/MT5_Account1",
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    assert r.mt5_path == "C:/MT5_Account1"


def test_account_update_accepts_mt5_path():
    from api.routes.accounts import AccountUpdate
    u = AccountUpdate(mt5_path="C:/MT5_Account2")
    assert u.mt5_path == "C:/MT5_Account2"


def test_account_update_mt5_path_none_by_default():
    from api.routes.accounts import AccountUpdate
    u = AccountUpdate()
    assert u.mt5_path is None
```

### Step 2: Run tests — expect failures

```bash
cd backend
uv run pytest tests/test_account_mt5_path.py -v
```

Expected: All 5 FAIL with `ValidationError` or `TypeError` (field doesn't exist yet).

### Step 3: Update `accounts.py` schemas

**`AccountCreate`** — add field after `auto_trade_enabled`:
```python
mt5_path: str = ""
```

**`AccountUpdate`** — add field after `password`:
```python
mt5_path: str | None = Field(None, description="Path to terminal64.exe for this account. Leave empty to use global MT5_PATH.")
```

**`AccountResponse`** — add field after `auto_trade_enabled`:
```python
mt5_path: str
```

### Step 4: Update `create_account` in `accounts.py`

Inside `create_account`, in the `Account(...)` constructor call, add:
```python
mt5_path=payload.mt5_path,
```

### Step 5: Update `update_account` in `accounts.py`

After the `if payload.password is not None:` block, add:
```python
if payload.mt5_path is not None:
    account.mt5_path = payload.mt5_path
```

### Step 6: Update `_to_response` in `accounts.py`

In `_to_response()`, add to `AccountResponse(...)`:
```python
mt5_path=a.mt5_path,
```

### Step 7: Replace all `path=settings.mt5_path` in `accounts.py`

There are **2 occurrences** in `accounts.py` (in `get_mt5_account_info` and `list_symbols`). Replace both:

```python
# OLD
path=settings.mt5_path,
# NEW
path=account.mt5_path or settings.mt5_path,
```

### Step 8: Replace all `path=settings.mt5_path` in `ai_trading.py`

There are **3 occurrences** in `ai_trading.py` (lines 112, 151, 286). Replace all three with `path=account.mt5_path or settings.mt5_path`.

### Step 9: Run the tests — expect pass

```bash
uv run pytest tests/test_account_mt5_path.py -v
```

Expected: All 5 PASS.

### Step 10: Run full test suite — no regressions

```bash
uv run pytest -v
```

Expected: all previously passing tests still pass.

---

## Task 3: History Methods on `MT5Bridge`

**Files:**
- Modify: `backend/mt5/bridge.py`
- Create: `backend/tests/test_mt5_bridge_history.py`

### Step 1: Write failing tests

Create `backend/tests/test_mt5_bridge_history.py`:

```python
"""Tests for MT5Bridge history methods."""
import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mt5.bridge import AccountCredentials, MT5Bridge


def _make_creds() -> AccountCredentials:
    return AccountCredentials(login=12345, password="pw", server="srv")


def _make_deal(ticket: int, position_id: int, entry: int, deal_type: int,
               symbol: str = "EURUSD", volume: float = 0.1,
               price: float = 1.0850, profit: float = 0.0,
               ts: int = 1700000000) -> MagicMock:
    d = MagicMock()
    d._asdict.return_value = {
        "ticket": ticket, "position_id": position_id, "entry": entry,
        "type": deal_type, "symbol": symbol, "volume": volume,
        "price": price, "profit": profit, "commission": 0.0,
        "swap": 0.0, "time": ts,
    }
    return d


def test_bridge_has_history_deals_get():
    assert hasattr(MT5Bridge, "history_deals_get")


def test_bridge_has_history_orders_get():
    assert hasattr(MT5Bridge, "history_orders_get")


def test_history_deals_get_is_coroutine():
    assert asyncio.iscoroutinefunction(MT5Bridge.history_deals_get)


def test_history_orders_get_is_coroutine():
    assert asyncio.iscoroutinefunction(MT5Bridge.history_orders_get)


@pytest.mark.asyncio
async def test_history_deals_get_returns_dicts():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=90)
    date_to = datetime.now(UTC)
    deal = _make_deal(101, 200, 1, 1, profit=30.0)

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.history_deals_get.return_value = [deal]
        result = await bridge.history_deals_get(date_from, date_to)

    assert len(result) == 1
    assert result[0]["ticket"] == 101
    assert result[0]["profit"] == 30.0


@pytest.mark.asyncio
async def test_history_deals_get_returns_empty_on_none():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=90)
    date_to = datetime.now(UTC)

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.history_deals_get.return_value = None
        result = await bridge.history_deals_get(date_from, date_to)

    assert result == []


@pytest.mark.asyncio
async def test_history_orders_get_returns_dicts():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=90)
    date_to = datetime.now(UTC)
    order = MagicMock()
    order._asdict.return_value = {"ticket": 999, "symbol": "GBPUSD"}

    with patch("mt5.bridge.MT5_AVAILABLE", True), \
         patch("mt5.bridge.mt5") as mock_mt5:
        mock_mt5.history_orders_get.return_value = [order]
        result = await bridge.history_orders_get(date_from, date_to)

    assert len(result) == 1
    assert result[0]["ticket"] == 999


@pytest.mark.asyncio
async def test_history_deals_raises_when_mt5_unavailable():
    bridge = MT5Bridge(_make_creds())
    date_from = datetime.now(UTC) - timedelta(days=1)
    date_to = datetime.now(UTC)

    with patch("mt5.bridge.MT5_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="MetaTrader5 package is not installed"):
            await bridge.history_deals_get(date_from, date_to)
```

### Step 2: Run tests — expect failures

```bash
uv run pytest tests/test_mt5_bridge_history.py -v
```

Expected: Attribute-error failures for `history_deals_get` / `history_orders_get`.

### Step 3: Add methods to `MT5Bridge`

In `bridge.py`, after the `# ── Order operations` section (after `get_last_error`), add a new section:

```python
# ── History ───────────────────────────────────────────────────────────────

async def history_deals_get(self, date_from: datetime, date_to: datetime) -> list[dict]:
    """Fetch all closed deals in [date_from, date_to].

    Each deal is one fill leg. A completed position produces two deals
    sharing the same position_id: one DEAL_ENTRY_IN (entry=0) and one
    DEAL_ENTRY_OUT (entry=1). The OUT deal carries the realised profit.
    """
    self._require_mt5()
    deals = await self._run(mt5.history_deals_get, date_from, date_to)
    return [d._asdict() for d in deals] if deals else []

async def history_orders_get(self, date_from: datetime, date_to: datetime) -> list[dict]:
    """Fetch all historical orders in [date_from, date_to]."""
    self._require_mt5()
    orders = await self._run(mt5.history_orders_get, date_from, date_to)
    return [o._asdict() for o in orders] if orders else []
```

Also add `from datetime import datetime` to the imports at the top of `bridge.py` (it's not imported yet).

### Step 4: Run tests — expect pass

```bash
uv run pytest tests/test_mt5_bridge_history.py -v
```

Expected: All 8 PASS.

### Step 5: Run full suite

```bash
uv run pytest -v
```

Expected: no regressions.

---

## Task 4: `services/history_sync.py`

**Files:**
- Create: `backend/services/history_sync.py`
- Create: `backend/tests/test_history_sync.py`

### Step 1: Write failing tests

Create `backend/tests/test_history_sync.py`:

```python
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


# ── format_for_llm ─────────────────────────────────────────────────────────

def test_format_for_llm_empty():
    from services.history_sync import HistoryService
    result = HistoryService.format_for_llm([], [])
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
```

### Step 2: Run tests — expect failures

```bash
uv run pytest tests/test_history_sync.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.history_sync'`

### Step 3: Create `services/history_sync.py`

```python
"""History Sync Service — fetch MT5 closed deals, sync to DB, format for analytics/AI.

Responsibilities:
- get_raw_deals: connect MT5, fetch deals list
- sync_to_db: upsert closed positions into trades table (skips existing tickets)
- get_performance_summary: compute win rate / profit factor from deal list
- format_for_llm: format recent trades as text for LLM prompt context
"""
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt
from db.models import Account, Trade
from mt5.bridge import AccountCredentials, MT5Bridge

logger = logging.getLogger(__name__)

# MT5 deal entry constants
_DEAL_ENTRY_IN = 0
_DEAL_ENTRY_OUT = 1

# MT5 deal type constants
_DEAL_TYPE_BUY = 0
_DEAL_TYPE_SELL = 1


class HistoryService:
    # ── Public async methods ──────────────────────────────────────────────

    async def get_raw_deals(
        self, account: Account, days: int, db: AsyncSession
    ) -> list[dict]:
        """Connect to MT5 and return all deals for the last `days` days."""
        date_to = datetime.now(UTC)
        date_from = date_to - timedelta(days=days)

        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=account.mt5_path or settings.mt5_path,
        )
        async with MT5Bridge(creds) as bridge:
            deals = await bridge.history_deals_get(date_from, date_to)

        logger.info(
            "Fetched %d deals | account_id=%s days=%s",
            len(deals), account.id, days,
        )
        return deals

    async def sync_to_db(
        self, account: Account, days: int, db: AsyncSession
    ) -> dict[str, int]:
        """Fetch MT5 deals and upsert new closed positions into the trades table.

        Returns {"imported": N, "total_fetched": M}.
        Skips deals already present (upsert guard by ticket=position_id).
        Sets source="manual" on imported rows.
        """
        deals = await self.get_raw_deals(account, days, db)
        out_deals, in_by_pos = self._pair_deals(deals)

        imported = 0
        for out_deal in out_deals:
            position_id: int = out_deal["position_id"]

            # Upsert guard: skip if trade with this ticket already exists
            existing = (
                await db.execute(
                    select(Trade).where(
                        Trade.account_id == account.id,
                        Trade.ticket == position_id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                continue

            in_deal = in_by_pos.get(position_id)
            direction = (
                "BUY"
                if (in_deal and in_deal.get("type") == _DEAL_TYPE_BUY)
                else "SELL"
            )
            entry_price = float(in_deal["price"]) if in_deal else 0.0
            opened_at = (
                datetime.fromtimestamp(in_deal["time"], tz=UTC)
                if in_deal
                else datetime.now(UTC)
            )
            close_price = float(out_deal.get("price", 0.0))
            profit = (
                float(out_deal.get("profit", 0.0))
                + float(out_deal.get("commission", 0.0))
                + float(out_deal.get("swap", 0.0))
            )
            closed_at = datetime.fromtimestamp(out_deal["time"], tz=UTC)

            trade = Trade(
                account_id=account.id,
                ticket=position_id,
                symbol=out_deal.get("symbol", ""),
                direction=direction,
                volume=float(out_deal.get("volume", 0.0)),
                entry_price=entry_price,
                stop_loss=0.0,
                take_profit=0.0,
                close_price=close_price,
                profit=profit,
                opened_at=opened_at,
                closed_at=closed_at,
                source="manual",
                is_paper_trade=False,
            )
            db.add(trade)
            imported += 1

        if imported:
            await db.commit()
            logger.info(
                "Synced %d new trades from MT5 history | account_id=%s",
                imported, account.id,
            )

        return {"imported": imported, "total_fetched": len(deals)}

    # ── Pure helper methods (no I/O) ──────────────────────────────────────

    @staticmethod
    def _pair_deals(
        deals: list[dict],
    ) -> tuple[list[dict], dict[int, dict]]:
        """Split deals into OUT deals and a position_id→IN deal lookup.

        Returns (out_deals, in_deals_by_position_id).
        Only fully-closed positions (entry==DEAL_ENTRY_OUT) are returned
        in out_deals. Partially-closed (DEAL_ENTRY_INOUT) are treated as OUT.
        """
        out_deals: list[dict] = []
        in_by_pos: dict[int, dict] = {}

        for deal in deals:
            entry = deal.get("entry", -1)
            pos_id = deal.get("position_id", 0)
            if entry == _DEAL_ENTRY_IN:
                in_by_pos[pos_id] = deal
            elif entry == _DEAL_ENTRY_OUT or entry == 2:  # 2 = DEAL_ENTRY_INOUT
                out_deals.append(deal)

        return out_deals, in_by_pos

    @staticmethod
    def get_performance_summary(deals: list[dict]) -> dict[str, Any]:
        """Compute win rate, P&L, and profit factor from a deal list.

        Only OUT deals (entry==1) contribute to stats.
        """
        out_deals = [d for d in deals if d.get("entry") == _DEAL_ENTRY_OUT]
        if not out_deals:
            return {
                "trade_count": 0,
                "winning_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
            }

        profits = [float(d.get("profit", 0.0)) for d in out_deals]
        winning = [p for p in profits if p > 0]
        losing = [p for p in profits if p < 0]
        gross_profit = sum(winning)
        gross_loss = abs(sum(losing))
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else math.inf
        )

        return {
            "trade_count": len(out_deals),
            "winning_trades": len(winning),
            "win_rate": round(len(winning) / len(out_deals), 4),
            "total_pnl": round(sum(profits), 2),
            "profit_factor": round(profit_factor, 2) if not math.isinf(profit_factor) else math.inf,
        }

    @staticmethod
    def format_for_llm(
        out_deals: list[dict],
        in_by_pos: dict[int, dict],
        limit: int = 10,
    ) -> str:
        """Return a compact text block of the N most recent closed trades.

        Intended for injection into the LLM prompt as additional context.
        Returns empty string if no deals.
        """
        if not out_deals:
            return ""

        recent = sorted(out_deals, key=lambda d: d.get("time", 0), reverse=True)[:limit]
        lines = ["Recent closed trades (last 10):"]
        for d in recent:
            pos_id = d.get("position_id", 0)
            in_deal = in_by_pos.get(pos_id)
            direction = (
                "BUY"
                if (in_deal and in_deal.get("type") == _DEAL_TYPE_BUY)
                else "SELL"
            )
            profit = float(d.get("profit", 0.0))
            sign = "+" if profit >= 0 else ""
            symbol = d.get("symbol", "?")
            volume = d.get("volume", "?")
            ts = d.get("time", 0)
            date_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d") if ts else "?"
            lines.append(
                f"  - {symbol} {direction} {volume} lot | profit={sign}{profit:.2f} | {date_str}"
            )
        return "\n".join(lines)
```

### Step 4: Run tests — expect pass

```bash
uv run pytest tests/test_history_sync.py -v
```

Expected: All tests PASS.

### Step 5: Run full suite

```bash
uv run pytest -v
```

Expected: no regressions.

---

## Task 5: History API Endpoints

**Files:**
- Modify: `backend/api/routes/accounts.py`
- Create: `backend/tests/test_history_endpoints.py`

### Step 1: Write failing tests

Create `backend/tests/test_history_endpoints.py`:

```python
"""Tests for /history and /history/sync endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


def _mock_account():
    return MagicMock(
        id=1, login=12345, password_encrypted="enc",
        server="srv", mt5_path="", is_active=True,
    )


def test_get_history_endpoint_exists():
    from main import app
    client = TestClient(app)
    routes = [r.path for r in app.routes]
    assert any("/accounts/{account_id}/history" in r for r in routes)


def test_sync_history_endpoint_exists():
    from main import app
    routes = [r.path for r in app.routes]
    assert any("/accounts/{account_id}/history/sync" in r for r in routes)


@pytest.mark.asyncio
async def test_get_history_returns_deals():
    from main import app
    from httpx import AsyncClient, ASGITransport

    deals = [{"ticket": 1, "position_id": 100, "symbol": "EURUSD", "profit": 30.0}]
    mock_account = _mock_account()

    with patch("api.routes.accounts.HistoryService") as mock_svc_cls:
        mock_svc = MagicMock()
        mock_svc.get_raw_deals = AsyncMock(return_value=deals)
        mock_svc_cls.return_value = mock_svc

        with patch("api.routes.accounts.get_db") as mock_get_db:
            mock_db = AsyncMock()
            mock_db.get.return_value = mock_account
            mock_get_db.return_value.__aiter__ = AsyncMock(return_value=iter([mock_db]))

            async def override_db():
                yield mock_db

            app.dependency_overrides = {}
            from db.postgres import get_db as real_get_db
            app.dependency_overrides[real_get_db] = override_db

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/v1/accounts/1/history?days=30")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_sync_history_returns_imported_count():
    from main import app
    from httpx import AsyncClient, ASGITransport

    mock_account = _mock_account()

    with patch("api.routes.accounts.HistoryService") as mock_svc_cls:
        mock_svc = MagicMock()
        mock_svc.sync_to_db = AsyncMock(return_value={"imported": 5, "total_fetched": 12})
        mock_svc_cls.return_value = mock_svc

        from db.postgres import get_db as real_get_db

        async def override_db():
            mock_db = AsyncMock()
            mock_db.get.return_value = mock_account
            yield mock_db

        app.dependency_overrides[real_get_db] = override_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/accounts/1/history/sync")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 5
    assert data["total_fetched"] == 12
```

### Step 2: Run tests — expect failures

```bash
uv run pytest tests/test_history_endpoints.py -v
```

Expected: failures because routes don't exist yet.

### Step 3: Add endpoints to `accounts.py`

Add the import at the top of `accounts.py`:
```python
from services.history_sync import HistoryService
```

Add two new response schemas before the routes section:
```python
class HistorySyncResponse(BaseModel):
    imported: int
    total_fetched: int
```

Add two new routes after the `get_account_stats` route:

```python
@router.get("/{account_id}/history")
async def get_account_history(
    account_id: int,
    days: int = Query(90, ge=1, le=365, description="Number of days of history to fetch"),
    db: AsyncSession = Depends(get_db),
):
    """Return raw MT5 closed deals for the last N days.

    Each item is one deal dict from MT5. Use this for dashboard charts and analytics.
    Errors: 404 account not found, 502/503 MT5 unavailable.
    """
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    logger.info("Fetching MT5 history | account_id=%s days=%s", account_id, days)
    try:
        svc = HistoryService()
        deals = await svc.get_raw_deals(account, days, db)
    except RuntimeError as exc:
        logger.error("MT5 unavailable (history) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        logger.error("MT5 connect failed (history) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return deals


@router.post("/{account_id}/history/sync", response_model=HistorySyncResponse)
async def sync_account_history(
    account_id: int,
    days: int = Query(90, ge=1, le=365, description="Number of days to sync"),
    db: AsyncSession = Depends(get_db),
):
    """Sync MT5 closed trades into the local trades table.

    Skips trades already present (idempotent). Returns count of newly imported rows.
    Errors: 404 account not found, 502/503 MT5 unavailable.
    """
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    logger.info("Syncing MT5 history | account_id=%s days=%s", account_id, days)
    try:
        svc = HistoryService()
        result = await svc.sync_to_db(account, days, db)
    except RuntimeError as exc:
        logger.error("MT5 unavailable (sync) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except ConnectionError as exc:
        logger.error("MT5 connect failed (sync) | account_id=%s | %s", account_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    logger.info(
        "History sync complete | account_id=%s imported=%s total=%s",
        account_id, result["imported"], result["total_fetched"],
    )
    return result
```

### Step 4: Run tests — expect pass

```bash
uv run pytest tests/test_history_endpoints.py -v
```

Expected: All PASS.

### Step 5: Run full suite

```bash
uv run pytest -v
```

Expected: no regressions.

---

## Task 6: AI Context — Wire Trade History into LLM Prompt

**Files:**
- Modify: `backend/ai/orchestrator.py`
- Modify: `backend/services/ai_trading.py`
- Create: `backend/tests/test_history_ai_context.py`

### Step 1: Write failing tests

Create `backend/tests/test_history_ai_context.py`:

```python
"""Tests for trade history AI context wiring."""
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_analyze_market_accepts_trade_history_context():
    from ai.orchestrator import analyze_market
    sig = inspect.signature(analyze_market)
    assert "trade_history_context" in sig.parameters
    param = sig.parameters["trade_history_context"]
    assert param.default is None


def test_analyze_and_trade_calls_get_raw_deals():
    """analyze_and_trade signature must not break; history fetch is fire-and-forget."""
    import inspect
    from services.ai_trading import AITradingService
    sig = inspect.signature(AITradingService.analyze_and_trade)
    # Existing params must still be present
    assert "account_id" in sig.parameters
    assert "symbol" in sig.parameters
    assert "timeframe" in sig.parameters
    assert "db" in sig.parameters


@pytest.mark.asyncio
async def test_analyze_market_injects_history_in_prompt():
    """When trade_history_context is provided, it appears in the LLM input."""
    from ai.orchestrator import analyze_market
    captured_inputs = {}

    async def mock_chain_invoke(inputs):
        captured_inputs.update(inputs)
        return {
            "action": "HOLD", "entry": 1.0, "stop_loss": 0.99,
            "take_profit": 1.01, "confidence": 0.5, "rationale": "test", "timeframe": "M15",
        }

    with patch("ai.orchestrator._DEFAULT_CHAIN") as mock_chain:
        mock_chain.ainvoke = mock_chain_invoke
        await analyze_market(
            symbol="EURUSD", timeframe="M15", current_price=1.085,
            indicators={}, ohlcv=[],
            trade_history_context="Recent closed trades (last 10):\n  - EURUSD BUY profit=+30.0",
        )

    assert "history_section" in captured_inputs
    assert "EURUSD BUY" in captured_inputs["history_section"]


@pytest.mark.asyncio
async def test_analyze_market_empty_history_section_when_none():
    from ai.orchestrator import analyze_market
    captured_inputs = {}

    async def mock_chain_invoke(inputs):
        captured_inputs.update(inputs)
        return {
            "action": "HOLD", "entry": 1.0, "stop_loss": 0.99,
            "take_profit": 1.01, "confidence": 0.5, "rationale": "test", "timeframe": "M15",
        }

    with patch("ai.orchestrator._DEFAULT_CHAIN") as mock_chain:
        mock_chain.ainvoke = mock_chain_invoke
        await analyze_market(
            symbol="EURUSD", timeframe="M15", current_price=1.085,
            indicators={}, ohlcv=[],
        )

    assert captured_inputs["history_section"] == ""
```

### Step 2: Run tests — expect failures

```bash
uv run pytest tests/test_history_ai_context.py -v
```

Expected: `test_analyze_market_accepts_trade_history_context` fails (param missing).

### Step 3: Update `ai/orchestrator.py`

**Add `trade_history_context` parameter to `analyze_market`:**

In the function signature, after `news_context: str | None = None,` add:
```python
trade_history_context: str | None = None,
```

**Add `{history_section}` to `_HUMAN` template:**

After `{news_section}` in the `_HUMAN` string, add:
```
{history_section}
```

**Build `history_section` in the function body:**

After the `news_section = ...` line, add:
```python
history_section = trade_history_context if trade_history_context else ""
```

**Add `history_section` to the `chain.ainvoke(...)` call:**

In the dict passed to `raw: dict = await chain.ainvoke(...)`, add:
```python
"history_section": history_section,
```

### Step 4: Update `ai_trading.py` to fetch history and pass context

In `AITradingService.analyze_and_trade`, after the `recent_signals` block (around line 190) and before step 7 (LLM analysis), add:

```python
trade_history_context: str | None = None
try:
    from services.history_sync import HistoryService
    hist_svc = HistoryService()
    recent_deals = await hist_svc.get_raw_deals(account, days=30, db=db)
    _, in_by_pos = HistoryService._pair_deals(recent_deals)
    out_deals = [d for d in recent_deals if d.get("entry") == 1]
    trade_history_context = HistoryService.format_for_llm(out_deals, in_by_pos, limit=10) or None
except Exception as exc:
    logger.warning(
        "Could not fetch trade history for LLM context | account_id=%s: %s", account_id, exc
    )
```

Then update the `analyze_market(...)` call to pass the new parameter:
```python
trade_history_context=trade_history_context,
```

### Step 5: Run tests — expect pass

```bash
uv run pytest tests/test_history_ai_context.py -v
```

Expected: All PASS.

### Step 6: Run full suite — final check

```bash
uv run pytest -v
```

Expected: All tests pass, no regressions.

---

## Summary: Files Changed

| File | Change |
|---|---|
| `db/models.py` | Add `mt5_path` column |
| `alembic/versions/<hash>_add_mt5_path_to_accounts.py` | New migration |
| `mt5/bridge.py` | Add `history_deals_get`, `history_orders_get` + `datetime` import |
| `services/history_sync.py` | **New file** — `HistoryService` |
| `api/routes/accounts.py` | Schema updates, 2 new endpoints, HistoryService import |
| `services/ai_trading.py` | Fix 3× `path=settings.mt5_path`, add history context fetch |
| `ai/orchestrator.py` | Add `trade_history_context` param + `{history_section}` |
| `tests/test_account_mt5_path.py` | **New** |
| `tests/test_mt5_bridge_history.py` | **New** |
| `tests/test_history_sync.py` | **New** |
| `tests/test_history_endpoints.py` | **New** |
| `tests/test_history_ai_context.py` | **New** |
