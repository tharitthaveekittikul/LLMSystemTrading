# Dashboard Redesign & UI Improvements — Design Doc

**Date:** 2026-02-27
**Scope:** Dashboard grid redesign, accounts card improvements, signals symbol selector, auto-trade flag, equity poller

---

## Goal

Rebuild the dashboard into a proper trading terminal layout (KPI bar + equity chart + positions + trades), add a per-account auto-trade toggle, persist equity snapshots to QuestDB, improve the accounts card with inline live stats, and replace the signals symbol text input with a Market Watch dropdown.

---

## Architecture

### Backend Additions

#### 1. `auto_trade_enabled` on Account
- Add `auto_trade_enabled: bool = True` column to `accounts` table
- Alembic migration
- Exposed on `AccountResponse` and `AccountUpdate` schemas
- `AITradingService.analyze_and_trade()` checks the flag — if `False`, saves signal but skips order placement (distinct from kill switch which is a global hard stop)

#### 2. Equity Snapshot Poller (`services/equity_poller.py`)
- Background asyncio task started in `main.py` lifespan
- Loop interval: 60 seconds
- For each active account with MT5 credentials: connect MT5 → `account_info()` → write row to QuestDB `equity_snapshots` table → broadcast `equity_update` WebSocket event
- QuestDB table schema:
  ```sql
  CREATE TABLE IF NOT EXISTS equity_snapshots (
    account_id LONG,
    balance DOUBLE,
    equity DOUBLE,
    free_margin DOUBLE,
    margin_level DOUBLE,
    ts TIMESTAMP
  ) TIMESTAMP(ts) PARTITION BY DAY;
  ```
- Error handling: per-account errors are logged and skipped (one failing account does not stop polling of others)

#### 3. New API Endpoints
- `GET /api/v1/accounts/{id}/equity-history?hours=24`
  Queries QuestDB for equity snapshots; returns `[{ts: str, equity: float, balance: float}]`
- `GET /api/v1/accounts/{id}/stats`
  Queries `trades` table for closed trades; returns `{win_rate: float, total_pnl: float, trade_count: int, winning_trades: int}`

---

### Frontend Changes

#### Dashboard (`/app/page.tsx`)
Full grid redesign replacing the existing vertical stack.

**Layout:**
```
┌──────────────────────────────────────────────────────────┐
│  KillSwitchBanner (full width, only when active)         │
├────────────┬───────────┬───────────┬────────────┬────────┤
│  Balance   │  Equity   │ Float P&L │  Win Rate  │ Auto   │
│            │           │           │            │ Trade  │
├────────────┴─────┬─────┴───────────┴──────┬─────┴────────┤
│  Total P&L       │  Free Margin           │ Margin Level │
├──────────────────┴────────────────────────┴──────────────┤
│  Equity Curve Chart (full width, recharts LineChart)     │
├────────────────────────┬─────────────────────────────────┤
│  Open Positions        │  Recent Closed Trades           │
└────────────────────────┴─────────────────────────────────┘
```

**Data sources:**
| KPI | Source |
|-----|--------|
| Balance | WebSocket `equity_update` → Zustand `balance.balance` |
| Equity | WebSocket `equity_update` → Zustand `balance.equity` |
| Floating P&L | Computed: `sum(openPositions[].profit)` |
| Free Margin | WebSocket `equity_update` → Zustand `balance.free_margin` |
| Margin Level | WebSocket `equity_update` → Zustand `balance.margin_level` |
| Win Rate | `GET /accounts/{id}/stats` on account change |
| Total P&L | `GET /accounts/{id}/stats` on account change |
| Auto-Trade | `GET /accounts/{id}` initial load; toggle calls `PATCH /accounts/{id}` |

**Equity chart:**
- `recharts` `LineChart` with `ResponsiveContainer`
- On account selection: fetch `GET /accounts/{id}/equity-history?hours=24`
- On WebSocket `equity_update`: append new data point
- X-axis: time labels; Y-axis: equity value; tooltip on hover

**Open Positions:** existing `live-positions.tsx` component, placed in left column

**Recent Closed Trades:** new `recent-trades.tsx` component, right column
- Fetches `GET /api/v1/trades?account_id={id}&limit=10` (closed trades)
- Columns: Symbol, Direction, P&L, Close Time

#### Accounts Page (`/app/accounts/page.tsx`)
`AccountCard` gains an **inline stats row**:
- Loaded lazily via `useEffect` calling `accountsApi.getInfo(id)` on mount (same endpoint as MT5InfoSheet)
- Shows: Balance, Equity, Profit (color-coded green/red)
- Shows skeleton loaders while loading; silently hides row if MT5 unavailable (503/502)
- The existing "MT5 Info" button (full details sheet) remains

#### Signals Page (`/app/signals/page.tsx`)
Symbol input replaced with a controlled `<Select>` component:
- When account is selected: calls `GET /api/v1/accounts/{id}/symbols`
- Populates dropdown with sorted symbol names from Market Watch
- Shows loading state while fetching; falls back to text input on error
- Clears selection when account changes

---

## Component Files

**New backend files:**
- `services/equity_poller.py` — equity snapshot background task
- Route additions in `api/routes/accounts.py` — equity-history, stats endpoints

**New frontend files:**
- `components/dashboard/kpi-bar.tsx` — 8 KPI stat cards
- `components/dashboard/equity-chart.tsx` — recharts equity curve
- `components/dashboard/recent-trades.tsx` — closed trades table

**Modified frontend files:**
- `app/page.tsx` — new grid layout
- `components/accounts/account-card.tsx` — inline stats row
- `app/signals/page.tsx` — symbol Select dropdown
- `lib/api/accounts.ts` — add `getSymbols()`, `getEquityHistory()`, `getStats()`
- `hooks/use-trading-store.ts` — add `autoTradeEnabled` per-account or in balance state
- `types/trading.ts` — add `AccountStats`, `EquityPoint` types

**Modified backend files:**
- `db/models.py` — `auto_trade_enabled` on Account
- `api/routes/accounts.py` — new endpoints + schema updates
- `services/ai_trading.py` — check `auto_trade_enabled`
- `main.py` — start equity poller in lifespan

---

## Out of Scope (Deferred)
- Strategy Book
- Authentication on endpoints
- Mobile-optimised layout
