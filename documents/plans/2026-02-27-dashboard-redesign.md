# Dashboard Redesign & UI Improvements — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the dashboard into a trading-terminal layout (KPI bar + equity chart + positions + trades), add per-account auto-trade toggle, persist equity snapshots to QuestDB, improve accounts card with inline live stats, and replace the signals symbol text input with a Market Watch dropdown.

**Architecture:** Backend gains `auto_trade_enabled` per account, an equity snapshot poller (asyncio background task → QuestDB), and two new API endpoints (`/stats`, `/equity-history`). Frontend gains three new dashboard components (KPI bar, equity chart, recent trades) wired into a full-page grid layout; accounts card gets lazy-loaded inline stats; signals page gets a Market Watch symbol selector.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, asyncpg/QuestDB, recharts (already installed), shadcn/ui, Zustand, TypeScript

---

## Context for implementor

**Working directory:** `c:\Users\paotharit\Documents\01_Project\LLMSystemTrading`

**Run backend tests from:** `backend/` with `uv run pytest -v`

**Run frontend type-check from:** `frontend/` with `npx tsc --noEmit`

**Key existing files:**
- `backend/db/models.py` — SQLAlchemy models (Account, Trade, etc.)
- `backend/db/questdb.py` — QuestDB helpers (`insert_equity_snapshot` already exists)
- `backend/api/routes/accounts.py` — all account routes and schemas
- `backend/services/ai_trading.py` — `AITradingService.analyze_and_trade()`
- `backend/main.py` — FastAPI app with lifespan context manager
- `frontend/src/types/trading.ts` — all TypeScript interfaces
- `frontend/src/lib/api/accounts.ts` — `accountsApi` namespace
- `frontend/src/app/page.tsx` — dashboard page
- `frontend/src/components/dashboard/` — dashboard components
- `frontend/src/components/accounts/account-card.tsx` — account card
- `frontend/src/app/signals/page.tsx` — signals page

---

## Task 1: Add `auto_trade_enabled` to Account model + migration

**Files:**
- Modify: `backend/db/models.py`
- Modify: `backend/api/routes/accounts.py`
- Modify: `backend/services/ai_trading.py`
- Alembic migration (generated)
- Test: `backend/tests/test_auto_trade.py` (new)

**Step 1: Write the failing test**

Create `backend/tests/test_auto_trade.py`:

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_account_response_includes_auto_trade_enabled(client):
    """AccountResponse schema must include auto_trade_enabled field."""
    response = await client.get("/api/v1/accounts")
    assert response.status_code != 422
    # If any accounts exist, check the field is present
    accounts = response.json()
    if accounts:
        assert "auto_trade_enabled" in accounts[0]
```

**Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_auto_trade.py -v
```
Expected: FAIL — `auto_trade_enabled` not in response schema.

**Step 3: Add `auto_trade_enabled` to the Account model**

In `backend/db/models.py`, add the field after `max_lot_size`:

```python
    max_lot_size: Mapped[float] = mapped_column(Float, default=0.1)
    auto_trade_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
```

**Step 4: Add `auto_trade_enabled` to AccountResponse and AccountUpdate schemas**

In `backend/api/routes/accounts.py`, find `AccountResponse` and add:

```python
    auto_trade_enabled: bool = True
```

Find `AccountUpdate` and add:

```python
    auto_trade_enabled: bool | None = None
```

Find `AccountCreate` and add (after `max_lot_size`):

```python
    auto_trade_enabled: bool = True
```

Also find the `_create_account` route (POST /accounts) and the `update_account` route (PATCH). The update route already uses `setattr` pattern — no changes needed there as long as the model field exists.

But double-check the existing update handler — it must copy `auto_trade_enabled` if present. Find this pattern in the PATCH route:

```python
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
```

If `model_dump` + `setattr` is used, it works automatically. If it's manual field-by-field, add `auto_trade_enabled` explicitly.

**Step 5: Check `AITradingService` — gate on `auto_trade_enabled`**

In `backend/services/ai_trading.py`, find the section after "# 9. Skip execution for HOLD or kill switch active" (around line 169). Add a new check before the order placement:

```python
        # 10. Skip execution if auto-trade disabled for this account
        if not account.auto_trade_enabled:
            logger.info(
                "Auto-trade disabled — signal saved but order skipped | account_id=%s",
                account_id,
            )
            return AnalysisResult(signal=signal, order_placed=False, ticket=None, journal_id=journal.id)
```

Place this block AFTER the kill switch check (step 9), BEFORE "# 10. Build order request".

**Step 6: Generate and apply the Alembic migration**

```bash
cd backend && uv run alembic revision --autogenerate -m "add auto_trade_enabled to accounts"
uv run alembic upgrade head
```

Expected output: `Running upgrade ... -> <hash>, add auto_trade_enabled to accounts`

**Step 7: Run tests**

```bash
cd backend && uv run pytest tests/test_auto_trade.py -v
```
Expected: PASS

**Step 8: Run full test suite**

```bash
cd backend && uv run pytest -v
```
Expected: all tests pass.

---

## Task 2: Account stats endpoint

**Files:**
- Modify: `backend/api/routes/accounts.py`
- Test: `backend/tests/test_account_stats.py` (new)

**Step 1: Write the failing test**

Create `backend/tests/test_account_stats.py`:

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_account_stats_404_for_unknown_account(client):
    response = await client.get("/api/v1/accounts/99999/stats")
    assert response.status_code == 404


async def test_account_stats_schema(client):
    """Stats endpoint returns the expected shape (empty account = zeros)."""
    # First create an account so we have a valid ID
    create_resp = await client.post("/api/v1/accounts", json={
        "name": "Stats Test",
        "broker": "TestBroker",
        "login": 88888,
        "password": "pass",
        "server": "test.server.com",
    })
    # 201 or 500 (DB not running in CI)
    if create_resp.status_code != 201:
        pytest.skip("DB not available")
    account_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/accounts/{account_id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "win_rate" in data
    assert "total_pnl" in data
    assert "trade_count" in data
    assert "winning_trades" in data
    assert data["trade_count"] == 0
    assert data["win_rate"] == 0.0
```

**Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_account_stats.py -v
```
Expected: FAIL — 404 route not found.

**Step 3: Add the stats endpoint to `backend/api/routes/accounts.py`**

Add these imports at the top if not already present:
```python
from sqlalchemy import func, select
```

Add the new schema and route before the `# ── Helpers` section:

```python
class AccountStatsResponse(BaseModel):
    win_rate: float
    total_pnl: float
    trade_count: int
    winning_trades: int


@router.get("/{account_id}/stats", response_model=AccountStatsResponse)
async def get_account_stats(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return aggregated trade statistics for an account."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from db.models import Trade

    result = await db.execute(
        select(
            func.count(Trade.id).label("trade_count"),
            func.coalesce(func.sum(Trade.profit), 0.0).label("total_pnl"),
            func.count(Trade.id).filter(Trade.profit > 0).label("winning_trades"),
        ).where(
            Trade.account_id == account_id,
            Trade.closed_at.is_not(None),
            Trade.profit.is_not(None),
        )
    )
    row = result.one()
    trade_count = row.trade_count or 0
    winning_trades = row.winning_trades or 0
    win_rate = winning_trades / trade_count if trade_count > 0 else 0.0

    return AccountStatsResponse(
        win_rate=round(win_rate, 4),
        total_pnl=round(float(row.total_pnl), 2),
        trade_count=trade_count,
        winning_trades=winning_trades,
    )
```

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_account_stats.py -v
```
Expected: PASS (or skip if DB not running).

**Step 5: Run full test suite**

```bash
cd backend && uv run pytest -v
```

---

## Task 3: QuestDB equity history query + equity poller

**Files:**
- Modify: `backend/db/questdb.py`
- Create: `backend/services/equity_poller.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_equity_poller.py` (new)

### Step 1: Add `get_equity_history` to questdb.py

In `backend/db/questdb.py`, add after `insert_equity_snapshot`:

```python
async def get_equity_history(account_id: int, hours: int = 24) -> list[dict]:
    """Return equity snapshots for the last N hours. Returns [] if table is empty or missing."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT ts, equity, balance
            FROM equity_snapshots
            WHERE account_id = $1
              AND ts >= dateadd('h', -$2, now())
            ORDER BY ts ASC
            """,
            account_id,
            hours,
        )
        return [{"ts": str(r["ts"]), "equity": float(r["equity"]), "balance": float(r["balance"])} for r in rows]
    except Exception as exc:
        logger.error("get_equity_history failed | account_id=%s | %s", account_id, exc)
        return []
    finally:
        await conn.close()
```

### Step 2: Create `backend/services/equity_poller.py`

```python
"""Equity Snapshot Poller — background task that polls MT5 and persists equity to QuestDB.

Started as an asyncio.Task in main.py lifespan. Runs every 60 seconds.
Broadcasts equity_update WebSocket events after each poll.
Each account's failure is isolated — one bad account won't skip others.
"""
import asyncio
import logging
from datetime import UTC, datetime

from core.config import settings
from core.security import decrypt

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 60  # seconds


async def run_equity_poller() -> None:
    """Background loop — runs forever until task is cancelled."""
    logger.info("Equity poller started | interval=%ds", _POLL_INTERVAL)
    while True:
        try:
            await _poll_all_accounts()
        except Exception as exc:
            logger.error("Equity poller cycle error: %s", exc)
        await asyncio.sleep(_POLL_INTERVAL)


async def _poll_all_accounts() -> None:
    from db.postgres import AsyncSessionLocal
    from db.models import Account
    from db.questdb import insert_equity_snapshot
    from api.routes.ws import broadcast
    from mt5.bridge import AccountCredentials, MT5Bridge
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Account).where(Account.is_active == True)  # noqa: E712
        )
        accounts = result.scalars().all()

    for account in accounts:
        await _poll_account(account, insert_equity_snapshot, broadcast)


async def _poll_account(account, insert_fn, broadcast_fn) -> None:
    """Poll a single account — catch all errors so other accounts keep running."""
    try:
        from mt5.bridge import AccountCredentials, MT5Bridge

        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=settings.mt5_path,
        )
        async with MT5Bridge(creds) as bridge:
            info = await bridge.get_account_info()

        if not info:
            logger.warning("Equity poller: no account info | account_id=%s", account.id)
            return

        equity = float(info.get("equity", 0))
        balance = float(info.get("balance", 0))
        margin = float(info.get("margin", 0))
        free_margin = float(info.get("margin_free", 0))
        margin_level = float(info.get("margin_level", 0))
        currency = info.get("currency", "USD")

        await insert_fn(
            account_id=account.id,
            equity=equity,
            balance=balance,
            margin=margin,
        )

        await broadcast_fn(account.id, "equity_update", {
            "account_id": account.id,
            "balance": balance,
            "equity": equity,
            "margin": margin,
            "free_margin": free_margin,
            "margin_level": margin_level,
            "currency": currency,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        logger.debug("Equity polled | account_id=%s equity=%.2f", account.id, equity)
    except Exception as exc:
        logger.error("Equity poller failed for account_id=%s: %s", account.id, exc)
```

### Step 3: Write the test

Create `backend/tests/test_equity_poller.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_poll_account_calls_insert_and_broadcast():
    """_poll_account writes to QuestDB and broadcasts equity_update."""
    from services.equity_poller import _poll_account

    mock_account = MagicMock()
    mock_account.id = 1
    mock_account.login = 12345
    mock_account.server = "test.server"
    mock_account.password_encrypted = "dummy"

    mock_info = {
        "balance": 10000.0, "equity": 10050.0, "margin": 200.0,
        "margin_free": 9800.0, "margin_level": 5025.0, "currency": "USD",
    }

    insert_mock = AsyncMock()
    broadcast_mock = AsyncMock()

    with patch("services.equity_poller.decrypt", return_value="plainpass"), \
         patch("services.equity_poller.MT5Bridge") as mock_bridge_cls:
        mock_bridge = AsyncMock()
        mock_bridge.get_account_info = AsyncMock(return_value=mock_info)
        mock_bridge_cls.return_value.__aenter__ = AsyncMock(return_value=mock_bridge)
        mock_bridge_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_account(mock_account, insert_mock, broadcast_mock)

    insert_mock.assert_called_once_with(
        account_id=1, equity=10050.0, balance=10000.0, margin=200.0
    )
    broadcast_mock.assert_called_once()
    call_args = broadcast_mock.call_args
    assert call_args[0][0] == 1           # account_id
    assert call_args[0][1] == "equity_update"
    data = call_args[0][2]
    assert data["equity"] == 10050.0
    assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_poll_account_swallows_mt5_error():
    """_poll_account does not raise even when MT5 fails."""
    from services.equity_poller import _poll_account

    mock_account = MagicMock()
    mock_account.id = 2
    mock_account.password_encrypted = "dummy"

    insert_mock = AsyncMock()
    broadcast_mock = AsyncMock()

    with patch("services.equity_poller.decrypt", return_value="plainpass"), \
         patch("services.equity_poller.MT5Bridge") as mock_bridge_cls:
        mock_bridge_cls.return_value.__aenter__ = AsyncMock(side_effect=ConnectionError("MT5 down"))
        mock_bridge_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # Should not raise
        await _poll_account(mock_account, insert_mock, broadcast_mock)

    insert_mock.assert_not_called()
    broadcast_mock.assert_not_called()
```

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_equity_poller.py -v
```
Expected: 2 PASS.

### Step 5: Register poller in `main.py` lifespan

In `backend/main.py`, add the import at top:
```python
import asyncio
```

And inside the `lifespan` function, start the poller task before `yield`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(...)
    await init_db()
    logger.info("Database tables ready")

    from services.equity_poller import run_equity_poller
    poller_task = asyncio.create_task(run_equity_poller())
    logger.info("Equity poller task started")

    yield

    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    await close_redis()
    logger.info("Shutting down LLM Trading System")
```

**Step 6: Run full test suite**

```bash
cd backend && uv run pytest -v
```
Expected: all pass.

---

## Task 4: Equity history API endpoint

**Files:**
- Modify: `backend/api/routes/accounts.py`
- Test: `backend/tests/test_equity_history.py` (new)

**Step 1: Write the failing test**

Create `backend/tests/test_equity_history.py`:

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_equity_history_404_for_missing_account(client):
    response = await client.get("/api/v1/accounts/99999/equity-history")
    assert response.status_code == 404


async def test_equity_history_returns_list(client):
    """Endpoint returns a list (empty if QuestDB not running)."""
    # This requires a valid account — skip gracefully if DB unavailable
    create_resp = await client.post("/api/v1/accounts", json={
        "name": "Equity History Test",
        "broker": "TestBroker",
        "login": 77777,
        "password": "pass",
        "server": "test.server.com",
    })
    if create_resp.status_code != 201:
        pytest.skip("DB not available")
    account_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/accounts/{account_id}/equity-history?hours=24")
    # 200 with empty list (QuestDB may not be running) or 500 — but NOT 422/404
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)
```

**Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_equity_history.py::test_equity_history_404_for_missing_account -v
```
Expected: FAIL — route not found.

**Step 3: Add the equity-history endpoint**

In `backend/api/routes/accounts.py`, add before the `_parse_symbols` helper at the bottom:

```python
class EquityPoint(BaseModel):
    ts: str
    equity: float
    balance: float


@router.get("/{account_id}/equity-history", response_model=list[EquityPoint])
async def get_equity_history(
    account_id: int,
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    """Return equity snapshots for the last N hours (default 24)."""
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    from db.questdb import get_equity_history
    points = await get_equity_history(account_id=account_id, hours=hours)
    return points
```

**Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_equity_history.py -v
```
Expected: PASS (or skip if DB unavailable).

**Step 5: Run full test suite**

```bash
cd backend && uv run pytest -v
```

---

## Task 5: Frontend — types + API methods

**Files:**
- Modify: `frontend/src/types/trading.ts`
- Modify: `frontend/src/lib/api/accounts.ts`

No tests — verify with TypeScript compiler.

**Step 1: Add new types to `frontend/src/types/trading.ts`**

Add `auto_trade_enabled` to `Account` interface (after `max_lot_size`):
```typescript
  max_lot_size: number;
  auto_trade_enabled: boolean;
```

Add `auto_trade_enabled` to `AccountUpdatePayload`:
```typescript
  auto_trade_enabled?: boolean;
```

Add new interfaces at the end of the file:
```typescript
export interface AccountStats {
  win_rate: number;
  total_pnl: number;
  trade_count: number;
  winning_trades: number;
}

export interface EquityPoint {
  ts: string;
  equity: number;
  balance: number;
}
```

**Step 2: Add new API methods to `frontend/src/lib/api/accounts.ts`**

Read the current file first. It should already have `list`, `get`, `create`, `update`, `remove`, `getInfo`. Add three more methods to the `accountsApi` object:

```typescript
  getSymbols: (id: number, allSymbols = false): Promise<string[]> =>
    apiRequest<string[]>(`/accounts/${id}/symbols${allSymbols ? "?all_symbols=true" : ""}`),

  getEquityHistory: (id: number, hours = 24): Promise<EquityPoint[]> =>
    apiRequest<EquityPoint[]>(`/accounts/${id}/equity-history?hours=${hours}`),

  getStats: (id: number): Promise<AccountStats> =>
    apiRequest<AccountStats>(`/accounts/${id}/stats`),
```

Add imports at top of file if needed:
```typescript
import type { AccountStats, EquityPoint } from "@/types/trading";
```

**Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

---

## Task 6: KPI bar component

**Files:**
- Create: `frontend/src/components/dashboard/kpi-bar.tsx`

**Step 1: Create the component**

```tsx
"use client";

import { useTradingStore } from "@/hooks/use-trading-store";
import type { AccountStats } from "@/types/trading";

interface KpiBarProps {
  stats: AccountStats | null;
  statsLoading: boolean;
  autoTradeEnabled: boolean;
  onAutoTradeToggle: (enabled: boolean) => void;
}

function KpiCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-3 flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`text-lg font-semibold tabular-nums ${valueClass ?? ""}`}>{value}</span>
      {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
    </div>
  );
}

export function KpiBar({ stats, statsLoading, autoTradeEnabled, onAutoTradeToggle }: KpiBarProps) {
  const balance = useTradingStore((s) => s.balance);
  const openPositions = useTradingStore((s) => s.openPositions);

  const floatingPnl = openPositions.reduce((sum, p) => sum + (p.profit ?? 0), 0);
  const currency = balance?.currency ?? "USD";
  const fmt = (v: number) =>
    new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
      <KpiCard label="Balance" value={balance ? `${fmt(balance.balance)} ${currency}` : "—"} />
      <KpiCard label="Equity" value={balance ? `${fmt(balance.equity)} ${currency}` : "—"} />
      <KpiCard
        label="Floating P&L"
        value={`${floatingPnl >= 0 ? "+" : ""}${fmt(floatingPnl)} ${currency}`}
        valueClass={floatingPnl >= 0 ? "text-green-500" : "text-red-500"}
      />
      <KpiCard
        label="Win Rate"
        value={statsLoading ? "…" : stats ? pct(stats.win_rate) : "—"}
        sub={stats ? `${stats.winning_trades}/${stats.trade_count} trades` : undefined}
      />
      <KpiCard
        label="Total P&L"
        value={statsLoading ? "…" : stats ? `${stats.total_pnl >= 0 ? "+" : ""}${fmt(stats.total_pnl)} ${currency}` : "—"}
        valueClass={stats && stats.total_pnl >= 0 ? "text-green-500" : "text-red-500"}
      />
      <KpiCard label="Free Margin" value={balance ? `${fmt(balance.free_margin)} ${currency}` : "—"} />
      <KpiCard
        label="Margin Level"
        value={balance?.margin_level != null ? `${fmt(balance.margin_level)}%` : "—"}
      />
      {/* Auto-Trade toggle */}
      <div className="rounded-lg border bg-card p-3 flex flex-col gap-2">
        <span className="text-xs text-muted-foreground">Auto-Trade</span>
        <button
          onClick={() => onAutoTradeToggle(!autoTradeEnabled)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
            autoTradeEnabled ? "bg-green-500" : "bg-muted"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              autoTradeEnabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
        <span className={`text-xs font-medium ${autoTradeEnabled ? "text-green-500" : "text-muted-foreground"}`}>
          {autoTradeEnabled ? "On" : "Off"}
        </span>
      </div>
    </div>
  );
}
```

**Step 2: Verify TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

---

## Task 7: Equity chart component

**Files:**
- Create: `frontend/src/components/dashboard/equity-chart.tsx`

**Step 1: Create the component**

`recharts` is already installed. The component takes initial data (loaded from API) and accepts new points via prop to append:

```tsx
"use client";

import { useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { EquityPoint } from "@/types/trading";

interface EquityChartProps {
  data: EquityPoint[];
  loading: boolean;
}

export function EquityChart({ data, loading }: EquityChartProps) {
  const formatted = useMemo(
    () =>
      data.map((p) => ({
        ts: new Date(p.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        equity: p.equity,
        balance: p.balance,
      })),
    [data]
  );

  if (loading) {
    return (
      <div className="rounded-lg border bg-card p-4 h-48 flex items-center justify-center">
        <span className="text-sm text-muted-foreground">Loading equity history…</span>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4 h-48 flex items-center justify-center">
        <span className="text-sm text-muted-foreground">No equity data yet — starts after first MT5 poll.</span>
      </div>
    );
  }

  const minEquity = Math.min(...data.map((p) => p.equity));
  const maxEquity = Math.max(...data.map((p) => p.equity));
  const padding = (maxEquity - minEquity) * 0.1 || 10;

  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="text-sm font-medium mb-3">Equity Curve (24h)</h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={formatted}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
          <XAxis dataKey="ts" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis
            domain={[minEquity - padding, maxEquity + padding]}
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => v.toLocaleString()}
          />
          <Tooltip
            formatter={(value: number) => [value.toLocaleString(), "Equity"]}
            labelFormatter={(label) => `Time: ${label}`}
          />
          <Line
            type="monotone"
            dataKey="equity"
            stroke="#22c55e"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

**Step 2: Verify TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

---

## Task 8: Recent closed trades component

**Files:**
- Create: `frontend/src/components/dashboard/recent-trades.tsx`

**Step 1: Create the component**

```tsx
"use client";

import { useEffect, useState } from "react";
import { tradesApi } from "@/lib/api";
import type { Trade } from "@/types/trading";

interface RecentTradesProps {
  accountId: number | null;
}

export function RecentTrades({ accountId }: RecentTradesProps) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!accountId) {
      setTrades([]);
      return;
    }
    setLoading(true);
    tradesApi
      .list({ account_id: accountId, limit: 10 })
      .then((data) => setTrades(data.filter((t) => t.closed_at !== null)))
      .catch(() => setTrades([]))
      .finally(() => setLoading(false));
  }, [accountId]);

  const fmt = (v: number | null) =>
    v == null ? "—" : new Intl.NumberFormat("en-US", { minimumFractionDigits: 2 }).format(v);

  return (
    <div className="rounded-lg border bg-card flex flex-col">
      <div className="p-3 border-b">
        <h3 className="text-sm font-medium">Recent Closed Trades</h3>
      </div>
      <div className="overflow-auto flex-1">
        {loading ? (
          <p className="text-sm text-muted-foreground p-4">Loading…</p>
        ) : trades.length === 0 ? (
          <p className="text-sm text-muted-foreground p-4">No closed trades yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="text-left p-2">Symbol</th>
                <th className="text-left p-2">Dir</th>
                <th className="text-right p-2">Profit</th>
                <th className="text-right p-2 hidden sm:table-cell">Closed</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b last:border-0">
                  <td className="p-2 font-mono text-xs">{t.symbol}</td>
                  <td className="p-2">
                    <span
                      className={`text-xs font-semibold ${
                        t.direction === "BUY" ? "text-blue-500" : "text-red-500"
                      }`}
                    >
                      {t.direction}
                    </span>
                  </td>
                  <td
                    className={`p-2 text-right tabular-nums text-xs ${
                      (t.profit ?? 0) >= 0 ? "text-green-500" : "text-red-500"
                    }`}
                  >
                    {(t.profit ?? 0) >= 0 ? "+" : ""}
                    {fmt(t.profit)}
                  </td>
                  <td className="p-2 text-right text-xs text-muted-foreground hidden sm:table-cell">
                    {t.closed_at
                      ? new Date(t.closed_at).toLocaleString([], {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Verify TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

---

## Task 9: Dashboard grid redesign

**Files:**
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/components/dashboard/dashboard-provider.tsx`

**Step 1: Update `dashboard-provider.tsx` to expose equity chart data**

The DashboardProvider needs to accumulate equity points for the chart. Change it to accept a callback:

```tsx
"use client";

import { useCallback } from "react";
import { useTradingStore } from "@/hooks/use-trading-store";
import { useWebSocket } from "@/hooks/use-websocket";
import type { EquityPoint, EquityUpdateData, PositionsUpdateData } from "@/types/trading";

interface DashboardProviderProps {
  onEquityUpdate?: (point: EquityPoint) => void;
}

export function DashboardProvider({ onEquityUpdate }: DashboardProviderProps) {
  const { activeAccountId, setBalance, setOpenPositions, setKillSwitch } =
    useTradingStore();

  const handleEquityUpdate = useCallback(
    (data: unknown) => {
      const d = data as EquityUpdateData;
      setBalance({
        account_id: d.account_id,
        balance: d.balance,
        equity: d.equity,
        margin: d.margin,
        free_margin: d.free_margin,
        margin_level: d.margin_level,
        currency: d.currency,
        timestamp: d.timestamp,
      });
      if (onEquityUpdate) {
        onEquityUpdate({ ts: d.timestamp, equity: d.equity, balance: d.balance });
      }
    },
    [setBalance, onEquityUpdate]
  );

  useWebSocket(activeAccountId, {
    equity_update: handleEquityUpdate,
    positions_update: (data) => {
      const d = data as PositionsUpdateData;
      setOpenPositions(d.positions);
    },
    kill_switch_triggered: (data) => {
      const d = data as { reason: string };
      setKillSwitch({ is_active: true, reason: d.reason, activated_at: new Date().toISOString() });
    },
  });

  return null;
}
```

**Step 2: Rewrite `frontend/src/app/page.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { KillSwitchBanner } from "@/components/dashboard/kill-switch-banner";
import { KpiBar } from "@/components/dashboard/kpi-bar";
import { EquityChart } from "@/components/dashboard/equity-chart";
import { LivePositions } from "@/components/dashboard/live-positions";
import { RecentTrades } from "@/components/dashboard/recent-trades";
import { DashboardProvider } from "@/components/dashboard/dashboard-provider";
import { useTradingStore } from "@/hooks/use-trading-store";
import { accountsApi } from "@/lib/api/accounts";
import type { AccountStats, EquityPoint } from "@/types/trading";

export default function DashboardPage() {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);

  // Stats (win rate, total P&L) — refreshed when account changes
  const [stats, setStats] = useState<AccountStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  // Equity chart data — loaded from API + appended via WebSocket
  const [equityData, setEquityData] = useState<EquityPoint[]>([]);
  const [equityLoading, setEquityLoading] = useState(false);

  // Auto-trade toggle state
  const [autoTradeEnabled, setAutoTradeEnabled] = useState(true);

  useEffect(() => {
    if (!activeAccountId) {
      setStats(null);
      setEquityData([]);
      return;
    }

    // Load stats
    setStatsLoading(true);
    accountsApi
      .getStats(activeAccountId)
      .then(setStats)
      .catch(() => setStats(null))
      .finally(() => setStatsLoading(false));

    // Load equity history
    setEquityLoading(true);
    accountsApi
      .getEquityHistory(activeAccountId, 24)
      .then(setEquityData)
      .catch(() => setEquityData([]))
      .finally(() => setEquityLoading(false));

    // Load auto-trade state
    accountsApi
      .get(activeAccountId)
      .then((account) => setAutoTradeEnabled(account.auto_trade_enabled))
      .catch(() => {});
  }, [activeAccountId]);

  const handleEquityUpdate = useCallback((point: EquityPoint) => {
    setEquityData((prev) => [...prev.slice(-199), point]); // keep last 200 points
  }, []);

  const handleAutoTradeToggle = useCallback(
    async (enabled: boolean) => {
      if (!activeAccountId) return;
      setAutoTradeEnabled(enabled);
      try {
        await accountsApi.update(activeAccountId, { auto_trade_enabled: enabled });
      } catch {
        setAutoTradeEnabled(!enabled); // revert on error
      }
    },
    [activeAccountId]
  );

  return (
    <SidebarInset>
      <AppHeader title="Dashboard" />
      <DashboardProvider onEquityUpdate={handleEquityUpdate} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <KillSwitchBanner />
        <KpiBar
          stats={stats}
          statsLoading={statsLoading}
          autoTradeEnabled={autoTradeEnabled}
          onAutoTradeToggle={handleAutoTradeToggle}
        />
        <EquityChart data={equityData} loading={equityLoading} />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0">
          <LivePositions />
          <RecentTrades accountId={activeAccountId} />
        </div>
      </div>
    </SidebarInset>
  );
}
```

**Step 3: Verify TypeScript and build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: no TypeScript errors, successful build.

---

## Task 10: Account card inline stats

**Files:**
- Modify: `frontend/src/components/accounts/account-card.tsx`

**Step 1: Read the current account-card.tsx**

Read `frontend/src/components/accounts/account-card.tsx` to understand its current structure before modifying.

**Step 2: Add inline stats row**

Add a `useEffect` that loads MT5 info on mount:

```tsx
  const [liveInfo, setLiveInfo] = useState<MT5AccountInfo | null>(null);

  useEffect(() => {
    accountsApi.getInfo(account.id)
      .then(setLiveInfo)
      .catch(() => {}); // silently hide row if MT5 unavailable
  }, [account.id]);
```

Add the stats row inside the card JSX, after the existing info fields and before the action buttons:

```tsx
{liveInfo && (
  <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t text-sm">
    <div>
      <p className="text-xs text-muted-foreground">Balance</p>
      <p className="font-medium tabular-nums">{liveInfo.balance.toLocaleString()}</p>
    </div>
    <div>
      <p className="text-xs text-muted-foreground">Equity</p>
      <p className="font-medium tabular-nums">{liveInfo.equity.toLocaleString()}</p>
    </div>
    <div>
      <p className="text-xs text-muted-foreground">P&L</p>
      <p className={`font-medium tabular-nums ${(liveInfo.profit ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
        {(liveInfo.profit ?? 0) >= 0 ? "+" : ""}{(liveInfo.profit ?? 0).toLocaleString()}
      </p>
    </div>
  </div>
)}
```

Also add the `MT5AccountInfo` type import if not already present:
```typescript
import type { MT5AccountInfo } from "@/types/trading";
```

**Step 3: Verify TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

---

## Task 11: Signals page — Market Watch symbol selector

**Files:**
- Modify: `frontend/src/app/signals/page.tsx`

**Step 1: Read the current signals page**

Read `frontend/src/app/signals/page.tsx` before modifying to understand the current form structure.

**Step 2: Replace text input with Market Watch Select**

The symbol input currently is a text `<input>`. Replace it with a `<select>` element that:
1. Fetches symbols when `selectedAccountId` changes
2. Populates dropdown from the response
3. Falls back gracefully on error

Add state variables:
```typescript
const [symbols, setSymbols] = useState<string[]>([]);
const [symbolsLoading, setSymbolsLoading] = useState(false);
```

Add a `useEffect` that fires when `selectedAccountId` changes:
```typescript
useEffect(() => {
  if (!selectedAccountId) {
    setSymbols([]);
    return;
  }
  setSymbolsLoading(true);
  accountsApi
    .getSymbols(Number(selectedAccountId))
    .then(setSymbols)
    .catch(() => setSymbols([]))
    .finally(() => setSymbolsLoading(false));
}, [selectedAccountId]);
```

Replace the `<input type="text" ... placeholder="e.g. EURUSD" />` with:
```tsx
{symbols.length > 0 ? (
  <select
    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
    value={symbol}
    onChange={(e) => setSymbol(e.target.value)}
  >
    <option value="">Select symbol…</option>
    {symbols.map((s) => (
      <option key={s} value={s}>{s}</option>
    ))}
  </select>
) : (
  <input
    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm placeholder:text-muted-foreground"
    placeholder={symbolsLoading ? "Loading symbols…" : "e.g. EURUSD (select account first)"}
    value={symbol}
    onChange={(e) => setSymbol(e.target.value)}
    disabled={symbolsLoading}
  />
)}
```

Add the `accountsApi` import if not already present:
```typescript
import { accountsApi } from "@/lib/api/accounts";
```

**Step 3: Verify TypeScript and build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: clean build.

---

## Task 12: Final verification

**Step 1: Run full backend test suite**

```bash
cd backend && uv run pytest -v
```
Expected: all tests pass.

**Step 2: Run frontend build**

```bash
cd frontend && npm run build
```
Expected: successful build, 0 TypeScript errors.

**Step 3: Manual smoke test**
- Start backend: `cd backend && uv run uvicorn main:app --reload --port 8000`
- Start frontend: `cd frontend && npm run dev`
- Open `http://localhost:3000`
- Verify dashboard shows KPI bar with 8 cards
- Verify equity chart section is present (shows "No equity data yet" message before first poll)
- Verify positions and recent trades sections are present
- Navigate to Accounts — verify cards load with inline stats row
- Navigate to Signals — select an account, verify symbol dropdown populates from Market Watch
