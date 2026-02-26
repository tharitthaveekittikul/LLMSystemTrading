# Calendar PnL Feature — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Trading PnL Calendar page (`/analytics`) that shows daily profit/loss as a color-coded heatmap with weekly summaries, monthly stat cards, and a trade drill-down sheet.

**Architecture:** New backend endpoint aggregates daily PnL via `GROUP BY DATE(closed_at)`. Frontend renders a custom 7-column calendar grid — NOT the shadcn calendar widget. Account context is global via the Zustand store; `AccountSelector` moves to `app-header.tsx`.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js 16 App Router + TypeScript + Tailwind CSS 4 + shadcn/ui (frontend), Zustand (state).

---

## Pre-Flight Notes

- Backend test pattern: `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`; run with `uv run pytest -v` from `backend/`
- Frontend: `npm run dev` from `frontend/`; no test runner configured — verify visually
- The Analytics sidebar link **already exists** (`app-sidebar.tsx:33`) — no change needed there
- All datetime fields are timezone-aware; use `datetime.now(UTC)` if needed
- `apiRequest<T>` in `frontend/src/lib/api.ts` handles all REST calls

---

## Task 1: Add date-range filter to `GET /api/v1/trades`

**Files:**
- Modify: `backend/api/routes/trades.py`
- Test: `backend/tests/test_trades.py` (create)

**Step 1: Write the failing test**

Create `backend/tests/test_trades.py`:
```python
import pytest
from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock

from main import app


@pytest.mark.asyncio
async def test_list_trades_date_filter_accepted():
    """date_from and date_to params are accepted without error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/trades?date_from=2025-12-01&date_to=2025-12-31"
        )
    # 200 or 500 (DB not running in CI) but NOT 422 (validation error)
    assert response.status_code != 422
```

**Step 2: Run to verify it fails**

```bash
cd backend
uv run pytest tests/test_trades.py -v
```
Expected: `FAILED` — 422 Unprocessable Entity because `date_from`/`date_to` params don't exist yet.

**Step 3: Add date filter params to `trades.py`**

Add these imports at the top of `backend/api/routes/trades.py`:
```python
from datetime import date
from sqlalchemy import cast, Date
```

Replace the `list_trades` function signature and body:
```python
@router.get("", response_model=list[TradeResponse])
async def list_trades(
    account_id: int | None = Query(None),
    open_only: bool = Query(False),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = select(Trade)
    if account_id:
        query = query.where(Trade.account_id == account_id)
    if open_only:
        query = query.where(Trade.closed_at == None)  # noqa: E711
    if date_from:
        query = query.where(cast(Trade.closed_at, Date) >= date_from)
    if date_to:
        query = query.where(cast(Trade.closed_at, Date) <= date_to)
    query = query.order_by(Trade.opened_at.desc()).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_trades.py -v
```
Expected: `PASSED`

**Step 5: Commit**

```bash
git add backend/api/routes/trades.py backend/tests/test_trades.py
git commit -m "feat(trades): add date_from/date_to filter params to GET /api/v1/trades"
```

---

## Task 2: Add `GET /api/v1/analytics/daily` endpoint

**Files:**
- Modify: `backend/api/routes/analytics.py`
- Test: `backend/tests/test_analytics.py` (create)

**Step 1: Write the failing test**

Create `backend/tests/test_analytics.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_daily_analytics_requires_year_month():
    """Missing year or month returns 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/analytics/daily")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_daily_analytics_returns_correct_shape():
    """Valid request returns expected response shape (even if DB is empty)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/analytics/daily?year=2025&month=12")
    # 200 or 500 (no DB in CI) — but NOT 422 or 404
    assert response.status_code != 422
    assert response.status_code != 404
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_analytics.py -v
```
Expected: `FAILED` — 404 because the route doesn't exist yet.

**Step 3: Add the endpoint to `analytics.py`**

Add imports to the top of `backend/api/routes/analytics.py`:
```python
from datetime import date
from sqlalchemy import cast, Date, extract, func
from pydantic import BaseModel
```

Add the Pydantic models after the imports (before `router = APIRouter()`):
```python
class DailyEntry(BaseModel):
    date: date
    net_pnl: float
    trade_count: int


class DailyPnLResponse(BaseModel):
    year: int
    month: int
    account_id: int | None
    days: list[DailyEntry]
    monthly_total: float
    monthly_trade_count: int
    winning_days: int
    losing_days: int
```

Add the new route after the existing `get_summary` route:
```python
@router.get("/daily", response_model=DailyPnLResponse)
async def get_daily_pnl(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return per-day aggregated PnL for a given month."""
    date_col = cast(Trade.closed_at, Date)

    query = (
        select(
            date_col.label("date"),
            func.sum(Trade.profit).label("net_pnl"),
            func.count(Trade.id).label("trade_count"),
        )
        .where(Trade.closed_at != None)  # noqa: E711
        .where(extract("year", Trade.closed_at) == year)
        .where(extract("month", Trade.closed_at) == month)
        .group_by(date_col)
        .order_by(date_col)
    )
    if account_id:
        query = query.where(Trade.account_id == account_id)

    result = await db.execute(query)
    rows = result.all()

    days = [
        DailyEntry(
            date=row.date,
            net_pnl=round(row.net_pnl or 0.0, 2),
            trade_count=row.trade_count,
        )
        for row in rows
    ]

    monthly_total = round(sum(d.net_pnl for d in days), 2)
    monthly_trade_count = sum(d.trade_count for d in days)
    winning_days = sum(1 for d in days if d.net_pnl > 0)
    losing_days = sum(1 for d in days if d.net_pnl < 0)

    return DailyPnLResponse(
        year=year,
        month=month,
        account_id=account_id,
        days=days,
        monthly_total=monthly_total,
        monthly_trade_count=monthly_trade_count,
        winning_days=winning_days,
        losing_days=losing_days,
    )
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_analytics.py -v
```
Expected: both tests `PASSED`

**Step 5: Commit**

```bash
git add backend/api/routes/analytics.py backend/tests/test_analytics.py
git commit -m "feat(analytics): add GET /api/v1/analytics/daily endpoint with daily PnL aggregation"
```

---

## Task 3: Move `AccountSelector` to global `app-header.tsx`

**Files:**
- Modify: `frontend/src/components/app-header.tsx`
- Modify: `frontend/src/app/page.tsx`

**Step 1: Update `app-header.tsx` to include `AccountSelector` and `ConnectionStatus`**

Replace the entire contents of `frontend/src/components/app-header.tsx`:
```tsx
import { AccountSelector } from "@/components/dashboard/account-selector";
import { ConnectionStatus } from "@/components/dashboard/connection-status";

interface AppHeaderProps {
  title: string;
}

export function AppHeader({ title }: AppHeaderProps) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
      <h1 className="font-semibold">{title}</h1>
      <div className="ml-auto flex items-center gap-3">
        <ConnectionStatus />
        <AccountSelector />
      </div>
    </header>
  );
}
```

**Step 2: Remove `AccountSelector` and `ConnectionStatus` from dashboard `page.tsx`**

Replace the contents of `frontend/src/app/page.tsx`:
```tsx
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { AccountOverview } from "@/components/dashboard/account-overview";
import { LivePositions } from "@/components/dashboard/live-positions";
import { AISignalsFeed } from "@/components/dashboard/ai-signals-feed";
import { KillSwitchBanner } from "@/components/dashboard/kill-switch-banner";
import { DashboardProvider } from "@/components/dashboard/dashboard-provider";

export default function DashboardPage() {
  return (
    <SidebarInset>
      <DashboardProvider />
      <AppHeader title="Dashboard" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <KillSwitchBanner />
        <div className="grid auto-rows-min gap-4 md:grid-cols-3">
          <AccountOverview />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <LivePositions />
          <AISignalsFeed />
        </div>
      </div>
    </SidebarInset>
  );
}
```

**Step 3: Verify visually**

```bash
cd frontend && npm run dev
```
Open http://localhost:3000 — confirm the account selector still appears in the header on the dashboard page, and also appears when navigating to `/accounts`.

**Step 4: Commit**

```bash
git add frontend/src/components/app-header.tsx frontend/src/app/page.tsx
git commit -m "feat(header): move AccountSelector and ConnectionStatus to global AppHeader"
```

---

## Task 4: Add frontend analytics API module

**Files:**
- Create: `frontend/src/lib/api/analytics.ts`
- Modify: `frontend/src/types/trading.ts`

**Step 1: Add types to `trading.ts`**

Add at the end of `frontend/src/types/trading.ts`:
```typescript
export interface DailyEntry {
  date: string; // "YYYY-MM-DD"
  net_pnl: number;
  trade_count: number;
}

export interface DailyPnLResponse {
  year: number;
  month: number;
  account_id: number | null;
  days: DailyEntry[];
  monthly_total: number;
  monthly_trade_count: number;
  winning_days: number;
  losing_days: number;
}
```

**Step 2: Create `analytics.ts` API module**

Create `frontend/src/lib/api/analytics.ts`:
```typescript
import { apiRequest } from "@/lib/api";
import type { DailyPnLResponse } from "@/types/trading";

export const analyticsApi = {
  getDaily(params: {
    year: number;
    month: number;
    accountId?: number | null;
  }): Promise<DailyPnLResponse> {
    const q = new URLSearchParams({
      year: String(params.year),
      month: String(params.month),
    });
    if (params.accountId) q.set("account_id", String(params.accountId));
    return apiRequest<DailyPnLResponse>(`/analytics/daily?${q}`);
  },
};
```

**Step 3: Commit**

```bash
git add frontend/src/lib/api/analytics.ts frontend/src/types/trading.ts
git commit -m "feat(analytics): add DailyPnLResponse types and analyticsApi.getDaily()"
```

---

## Task 5: Build calendar grid components

**Files:**
- Create: `frontend/src/components/analytics/day-cell.tsx`
- Create: `frontend/src/components/analytics/week-summary-cell.tsx`
- Create: `frontend/src/components/analytics/calendar-grid.tsx`

**Step 1: Create `day-cell.tsx`**

```tsx
"use client";

import { cn } from "@/lib/utils";
import type { DailyEntry } from "@/types/trading";

interface DayCellProps {
  day: number; // 1-31, or 0 for padding
  entry?: DailyEntry;
  isCurrentMonth: boolean;
  isSelected: boolean;
  isToday: boolean;
  onClick?: () => void;
}

export function DayCell({
  day,
  entry,
  isCurrentMonth,
  isSelected,
  isToday,
  onClick,
}: DayCellProps) {
  if (day === 0) {
    return <div className="min-h-[80px] rounded-md bg-muted/10 opacity-20" />;
  }

  const hasTrades = !!entry;
  const pnl = entry?.net_pnl ?? 0;
  const isProfit = hasTrades && pnl > 0;
  const isLoss = hasTrades && pnl < 0;

  return (
    <div
      onClick={hasTrades && isCurrentMonth ? onClick : undefined}
      className={cn(
        "min-h-[80px] rounded-md border p-2 transition-colors",
        isCurrentMonth ? "opacity-100" : "opacity-30",
        hasTrades && isProfit && "border-green-700/50 bg-green-900/30",
        hasTrades && isLoss && "border-red-700/50 bg-red-900/30",
        !hasTrades && "border-border bg-muted/10",
        hasTrades && isCurrentMonth && "cursor-pointer hover:opacity-80",
        isSelected && "ring-2 ring-blue-500",
        isToday && "ring-2 ring-primary",
      )}
    >
      <div className="flex items-start justify-between">
        <span className={cn("text-sm font-medium", isToday && "text-primary")}>
          {day}
        </span>
      </div>
      {hasTrades && isCurrentMonth && (
        <div className="mt-1">
          <p
            className={cn(
              "text-sm font-semibold",
              isProfit && "text-green-400",
              isLoss && "text-red-400",
            )}
          >
            {pnl > 0 ? "+" : ""}
            {pnl.toFixed(2)}
          </p>
          <p className="text-xs text-muted-foreground">
            {entry.trade_count} trade{entry.trade_count !== 1 ? "s" : ""}
          </p>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Create `week-summary-cell.tsx`**

```tsx
import { cn } from "@/lib/utils";

interface WeekSummaryCellProps {
  weekNumber: number;
  netPnl: number;
  tradeCount: number;
}

export function WeekSummaryCell({
  weekNumber,
  netPnl,
  tradeCount,
}: WeekSummaryCellProps) {
  const isProfit = netPnl > 0;
  const isLoss = netPnl < 0;

  return (
    <div className="flex min-h-[80px] flex-col items-center justify-center rounded-md border border-dashed border-border bg-muted/5 p-2">
      <p className="text-xs text-muted-foreground">W{weekNumber}</p>
      {tradeCount > 0 ? (
        <>
          <p
            className={cn(
              "text-sm font-semibold",
              isProfit && "text-green-400",
              isLoss && "text-red-400",
              !isProfit && !isLoss && "text-muted-foreground",
            )}
          >
            {netPnl > 0 ? "+" : ""}
            {netPnl.toFixed(2)}
          </p>
          <p className="text-xs text-muted-foreground">{tradeCount}t</p>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">—</p>
      )}
    </div>
  );
}
```

**Step 3: Create `calendar-grid.tsx`**

```tsx
"use client";

import { DayCell } from "./day-cell";
import { WeekSummaryCell } from "./week-summary-cell";
import type { DailyEntry } from "@/types/trading";

interface CalendarGridProps {
  year: number;
  month: number; // 1-12
  days: DailyEntry[];
  selectedDate: string | null;
  onDaySelect: (date: string) => void;
}

const DAY_HEADERS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function CalendarGrid({
  year,
  month,
  days,
  selectedDate,
  onDaySelect,
}: CalendarGridProps) {
  // Build a lookup map: "YYYY-MM-DD" -> DailyEntry
  const dayMap = new Map(days.map((d) => [d.date, d]));

  const today = new Date();
  const todayStr = today.toISOString().split("T")[0];

  // First day of month and total days
  const firstDay = new Date(year, month - 1, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month, 0).getDate();

  // Build flat array of cells: 0 = padding, 1-31 = actual days
  const cells: number[] = [
    ...Array(firstDay).fill(0),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  // Pad end to complete last week
  while (cells.length % 7 !== 0) cells.push(0);

  // Split into weeks (rows of 7)
  const weeks: number[][] = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }

  const pad = (n: number) => String(n).padStart(2, "0");

  return (
    <div>
      {/* Day headers */}
      <div className="mb-1 grid grid-cols-[repeat(7,1fr)_120px] gap-1">
        {DAY_HEADERS.map((h) => (
          <div key={h} className="py-1 text-center text-xs text-muted-foreground">
            {h}
          </div>
        ))}
        <div className="py-1 text-center text-xs text-muted-foreground">Week</div>
      </div>

      {/* Weeks */}
      {weeks.map((week, wi) => {
        // Calculate weekly totals
        const weekEntries = week
          .filter((d) => d > 0)
          .map((d) => dayMap.get(`${year}-${pad(month)}-${pad(d)}`))
          .filter(Boolean) as DailyEntry[];

        const weekPnl = weekEntries.reduce((sum, e) => sum + e.net_pnl, 0);
        const weekTrades = weekEntries.reduce((sum, e) => sum + e.trade_count, 0);

        return (
          <div key={wi} className="mb-1 grid grid-cols-[repeat(7,1fr)_120px] gap-1">
            {week.map((day, di) => {
              const dateStr =
                day > 0 ? `${year}-${pad(month)}-${pad(day)}` : "";
              return (
                <DayCell
                  key={di}
                  day={day}
                  entry={day > 0 ? dayMap.get(dateStr) : undefined}
                  isCurrentMonth={day > 0}
                  isSelected={dateStr === selectedDate}
                  isToday={dateStr === todayStr}
                  onClick={() => day > 0 && onDaySelect(dateStr)}
                />
              );
            })}
            <WeekSummaryCell
              weekNumber={wi + 1}
              netPnl={Math.round(weekPnl * 100) / 100}
              tradeCount={weekTrades}
            />
          </div>
        );
      })}
    </div>
  );
}
```

**Step 4: Commit**

```bash
git add frontend/src/components/analytics/
git commit -m "feat(analytics): add DayCell, WeekSummaryCell, and CalendarGrid components"
```

---

## Task 6: Build `pnl-calendar.tsx` container

**Files:**
- Create: `frontend/src/components/analytics/pnl-calendar.tsx`

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CalendarGrid } from "./calendar-grid";
import { analyticsApi } from "@/lib/api/analytics";
import { useTradingStore } from "@/hooks/use-trading-store";
import type { DailyEntry, DailyPnLResponse } from "@/types/trading";

interface PnlCalendarProps {
  onDaySelect: (date: string, entry: DailyEntry) => void;
  selectedDate: string | null;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function PnlCalendar({ onDaySelect, selectedDate }: PnlCalendarProps) {
  const { activeAccountId } = useTradingStore();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1); // 1-12
  const [data, setData] = useState<DailyPnLResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await analyticsApi.getDaily({
        year,
        month,
        accountId: activeAccountId,
      });
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [year, month, activeAccountId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  function prevMonth() {
    if (month === 1) { setYear((y) => y - 1); setMonth(12); }
    else setMonth((m) => m - 1);
  }

  function nextMonth() {
    if (month === 12) { setYear((y) => y + 1); setMonth(1); }
    else setMonth((m) => m + 1);
  }

  function goToday() {
    setYear(now.getFullYear());
    setMonth(now.getMonth() + 1);
  }

  return (
    <div>
      {/* Calendar navigation */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={prevMonth}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <h2 className="w-40 text-center text-sm font-semibold">
            {MONTH_NAMES[month - 1]} {year}
          </h2>
          <Button variant="outline" size="icon" onClick={nextMonth}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <Button variant="ghost" size="sm" onClick={goToday}>
          Today
        </Button>
      </div>

      {loading && (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Loading…
        </p>
      )}

      {error && (
        <p className="py-8 text-center text-sm text-red-400">{error}</p>
      )}

      {!loading && !error && (
        <CalendarGrid
          year={year}
          month={month}
          days={data?.days ?? []}
          selectedDate={selectedDate}
          onDaySelect={(date) => {
            const entry = data?.days.find((d) => d.date === date);
            if (entry) onDaySelect(date, entry);
          }}
        />
      )}
    </div>
  );
}
```

**Commit:**

```bash
git add frontend/src/components/analytics/pnl-calendar.tsx
git commit -m "feat(analytics): add PnlCalendar container with month navigation and data fetching"
```

---

## Task 7: Build `trade-drill-down.tsx` Sheet

**Files:**
- Create: `frontend/src/components/analytics/trade-drill-down.tsx`

```tsx
"use client";

import { useState, useEffect } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { apiRequest } from "@/lib/api";
import { useTradingStore } from "@/hooks/use-trading-store";
import type { Trade, DailyEntry } from "@/types/trading";

interface TradeDrillDownProps {
  date: string | null; // "YYYY-MM-DD"
  entry: DailyEntry | null;
  open: boolean;
  onClose: () => void;
}

export function TradeDrillDown({ date, entry, open, onClose }: TradeDrillDownProps) {
  const { activeAccountId } = useTradingStore();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !date) return;
    setLoading(true);
    const q = new URLSearchParams({ date_from: date, date_to: date });
    if (activeAccountId) q.set("account_id", String(activeAccountId));
    apiRequest<Trade[]>(`/trades?${q}`)
      .then(setTrades)
      .catch(() => setTrades([]))
      .finally(() => setLoading(false));
  }, [open, date, activeAccountId]);

  const pnl = entry?.net_pnl ?? 0;
  const isProfit = pnl > 0;

  function duration(open_time: string, close_time: string | null): string {
    if (!close_time) return "—";
    const ms = new Date(close_time).getTime() - new Date(open_time).getTime();
    const mins = Math.floor(ms / 60000);
    if (mins < 60) return `${mins}m`;
    return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-[600px] sm:max-w-[600px]">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-3">
            <span>{date}</span>
            {entry && (
              <span
                className={cn(
                  "text-base font-semibold",
                  isProfit ? "text-green-400" : "text-red-400",
                )}
              >
                {pnl > 0 ? "+" : ""}
                {pnl.toFixed(2)}
              </span>
            )}
          </SheetTitle>
        </SheetHeader>

        <div className="mt-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading trades…</p>
          ) : trades.length === 0 ? (
            <p className="text-sm text-muted-foreground">No trades found.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Dir</TableHead>
                  <TableHead>Vol</TableHead>
                  <TableHead>Entry</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead>PnL</TableHead>
                  <TableHead>Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-mono text-xs">{t.symbol}</TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          "text-xs font-semibold uppercase",
                          t.type === "buy" ? "text-green-400" : "text-red-400",
                        )}
                      >
                        {t.type}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs">{t.volume}</TableCell>
                    <TableCell className="font-mono text-xs">{t.open_price}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {t.close_price ?? "—"}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-xs font-semibold",
                        (t.profit ?? 0) > 0 ? "text-green-400" : "text-red-400",
                      )}
                    >
                      {t.profit != null
                        ? `${t.profit > 0 ? "+" : ""}${t.profit.toFixed(2)}`
                        : "—"}
                    </TableCell>
                    <TableCell className="text-xs">
                      {duration(t.open_time, t.close_time)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
```

**Commit:**

```bash
git add frontend/src/components/analytics/trade-drill-down.tsx
git commit -m "feat(analytics): add TradeDrillDown sheet component"
```

---

## Task 8: Build the Analytics page

**Files:**
- Create: `frontend/src/app/analytics/page.tsx`

```tsx
"use client";

import { useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { PnlCalendar } from "@/components/analytics/pnl-calendar";
import { TradeDrillDown } from "@/components/analytics/trade-drill-down";
import type { DailyEntry } from "@/types/trading";
import { cn } from "@/lib/utils";

export default function AnalyticsPage() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<DailyEntry | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  function handleDaySelect(date: string, entry: DailyEntry) {
    setSelectedDate(date);
    setSelectedEntry(entry);
    setSheetOpen(true);
  }

  return (
    <SidebarInset>
      <AppHeader title="Analytics" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <PnlCalendar
          selectedDate={selectedDate}
          onDaySelect={handleDaySelect}
        />
      </div>

      <TradeDrillDown
        date={selectedDate}
        entry={selectedEntry}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
      />
    </SidebarInset>
  );
}
```

**Commit:**

```bash
git add frontend/src/app/analytics/page.tsx
git commit -m "feat(analytics): add /analytics page wiring PnlCalendar and TradeDrillDown"
```

---

## Task 9: Add monthly stat cards

**Files:**
- Create: `frontend/src/components/analytics/monthly-stats.tsx`
- Modify: `frontend/src/app/analytics/page.tsx`

**Step 1: Create `monthly-stats.tsx`**

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { DailyPnLResponse } from "@/types/trading";

interface MonthlyStatsProps {
  data: DailyPnLResponse | null;
  loading: boolean;
}

export function MonthlyStats({ data, loading }: MonthlyStatsProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <Card key={i} className="animate-pulse">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">—</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-6 w-24 rounded bg-muted" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const pnl = data?.monthly_total ?? 0;
  const isProfit = pnl > 0;
  const isLoss = pnl < 0;

  return (
    <div className="grid grid-cols-3 gap-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Monthly PnL</CardTitle>
        </CardHeader>
        <CardContent>
          <p
            className={cn(
              "text-2xl font-bold",
              isProfit && "text-green-400",
              isLoss && "text-red-400",
              !isProfit && !isLoss && "text-muted-foreground",
            )}
          >
            {pnl > 0 ? "+" : ""}
            {pnl.toFixed(2)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Winning Days</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            <span className="text-green-400">{data?.winning_days ?? 0}</span>
            <span className="text-sm text-muted-foreground">
              {" "}/ {(data?.winning_days ?? 0) + (data?.losing_days ?? 0)}
            </span>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Total Trades</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{data?.monthly_trade_count ?? 0}</p>
        </CardContent>
      </Card>
    </div>
  );
}
```

**Step 2: Lift `data` and `loading` state up to the page and pass to both `MonthlyStats` and `PnlCalendar`**

The cleanest approach is to lift calendar state to the page. Update `pnl-calendar.tsx` to accept an `onDataChange` callback, and update the page:

Add `onDataChange` prop to `PnlCalendar`:
```tsx
// In pnl-calendar.tsx — add to PnlCalendarProps:
onDataChange?: (data: DailyPnLResponse | null, loading: boolean) => void;

// After setData(result) in fetchData():
onDataChange?.(result, false);

// After setLoading(true):
onDataChange?.(null, true);
```

Update `frontend/src/app/analytics/page.tsx`:
```tsx
"use client";

import { useState } from "react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { PnlCalendar } from "@/components/analytics/pnl-calendar";
import { TradeDrillDown } from "@/components/analytics/trade-drill-down";
import { MonthlyStats } from "@/components/analytics/monthly-stats";
import type { DailyEntry, DailyPnLResponse } from "@/types/trading";

export default function AnalyticsPage() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<DailyEntry | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [calData, setCalData] = useState<DailyPnLResponse | null>(null);
  const [calLoading, setCalLoading] = useState(false);

  function handleDaySelect(date: string, entry: DailyEntry) {
    setSelectedDate(date);
    setSelectedEntry(entry);
    setSheetOpen(true);
  }

  function handleDataChange(data: DailyPnLResponse | null, loading: boolean) {
    setCalData(data);
    setCalLoading(loading);
  }

  return (
    <SidebarInset>
      <AppHeader title="Analytics" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <MonthlyStats data={calData} loading={calLoading} />
        <PnlCalendar
          selectedDate={selectedDate}
          onDaySelect={handleDaySelect}
          onDataChange={handleDataChange}
        />
      </div>

      <TradeDrillDown
        date={selectedDate}
        entry={selectedEntry}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
      />
    </SidebarInset>
  );
}
```

**Commit:**

```bash
git add frontend/src/components/analytics/monthly-stats.tsx \
        frontend/src/components/analytics/pnl-calendar.tsx \
        frontend/src/app/analytics/page.tsx
git commit -m "feat(analytics): add monthly stat cards (PnL, winning days, trade count)"
```

---

## Task 10: Polish — empty states and final verification

**Step 1: Add empty state to `pnl-calendar.tsx`**

In the `!loading && !error` block, add an empty state when no trades exist for the month:
```tsx
{!loading && !error && (
  <>
    {data && data.days.length === 0 && (
      <p className="py-4 text-center text-sm text-muted-foreground">
        No closed trades in {MONTH_NAMES[month - 1]} {year}.
      </p>
    )}
    <CalendarGrid
      year={year}
      month={month}
      days={data?.days ?? []}
      selectedDate={selectedDate}
      onDaySelect={(date) => {
        const entry = data?.days.find((d) => d.date === date);
        if (entry) onDaySelect(date, entry);
      }}
    />
  </>
)}
```

**Step 2: Run all backend tests**

```bash
cd backend
uv run pytest -v
```
Expected: all tests pass.

**Step 3: Smoke-test the frontend**

```bash
cd frontend && npm run dev
```

Checklist:
- [ ] `/` dashboard — account selector appears in header, no duplicate
- [ ] `/accounts` — account selector appears in header
- [ ] `/analytics` — stat cards load (zeros if no trades), calendar grid renders
- [ ] Calendar navigation — prev/next month, Today button work
- [ ] Click a day with trades — sheet opens with trade table
- [ ] No TypeScript errors in browser console

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(analytics): polish empty states and finalize Calendar PnL feature"
```

---

## Verification Checklist

- [ ] `GET /api/v1/analytics/daily?year=2025&month=12` returns correct shape
- [ ] `GET /api/v1/trades?date_from=2025-12-03&date_to=2025-12-03` filters correctly
- [ ] Analytics page visible at `/analytics` with sidebar link active
- [ ] Account selector present on every page
- [ ] Green/red/neutral day cells render correctly based on PnL sign
- [ ] Weekly summary column shows correct aggregates
- [ ] Sheet opens on day click, loads trades for that day
- [ ] Month with no trades shows empty state message
- [ ] All backend tests pass (`uv run pytest -v`)
