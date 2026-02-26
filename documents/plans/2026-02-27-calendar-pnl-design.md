# Calendar PnL Feature — Design Document

**Date:** 2026-02-27
**Status:** Approved

---

## Overview

A Trading PnL Calendar page (`/analytics`) showing daily profit/loss as a color-coded heatmap grid. Modeled after TopstepX. Includes weekly summaries, monthly stat cards, and a drill-down sheet for individual trades per day.

---

## Backend Changes

### New Endpoint: `GET /api/v1/analytics/daily`

**Query params:**
- `account_id` (int, optional) — filter by account; omit for all accounts
- `year` (int, required) — e.g. `2025`
- `month` (int, required, 1–12) — e.g. `12`

**Response schema:**
```json
{
  "year": 2025,
  "month": 12,
  "account_id": 1,
  "days": [
    { "date": "2025-12-03", "net_pnl": 142.50, "trade_count": 3 },
    { "date": "2025-12-07", "net_pnl": -67.00, "trade_count": 1 }
  ],
  "monthly_total": 75.50,
  "monthly_trade_count": 4,
  "winning_days": 1,
  "losing_days": 1
}
```

**Implementation notes:**
- Single `GROUP BY DATE(closed_at)` SQLAlchemy query on the `trades` table
- Filter: `closed_at IS NOT NULL` (closed trades only), within month window
- Lives in `backend/api/routes/analytics.py`
- Add `DailyPnLResponse` and `DailyEntry` Pydantic models

### Existing Route Tweak: `GET /api/v1/trades`

Add optional query params `date_from` (YYYY-MM-DD) and `date_to` (YYYY-MM-DD) to support fetching trades for a single day in the drill-down sheet.

---

## Frontend Architecture

### New Page
`src/app/analytics/page.tsx` — Analytics / Calendar PnL page

### New Sidebar Link
Add "Analytics" entry with a `CalendarDays` icon to `app-sidebar.tsx`, pointing to `/analytics`.

### Header Change
Move `AccountSelector` component from the dashboard into `app-header.tsx` so it appears globally on every page. The active account flows through the existing Zustand store (`activeAccountId`).

### New Components

```
src/components/analytics/
├── pnl-calendar.tsx          # Container: fetches data, owns month/selected-day state
├── calendar-grid.tsx         # Pure grid: generates 7-col layout for any month
├── day-cell.tsx              # Single day tile: date number, net PnL, trade count
├── week-summary-cell.tsx     # Rightmost column: weekly PnL + trade count totals
└── trade-drill-down.tsx      # shadcn Sheet: trade list for the selected day
```

### State Flow

1. `pnl-calendar` reads `activeAccountId` from Zustand store
2. On mount and on month/account change → `GET /api/v1/analytics/daily?account_id=&year=&month=`
3. Calendar grid renders with returned `days[]` data
4. User clicks a day → selected day state updates, Sheet opens
5. Sheet fetches `GET /api/v1/trades?account_id=&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

**No new state library** — plain `useState` + `useEffect`.

---

## Visual Design

### Page Layout

```
┌─────────────────────────────────────────────────────┐
│ Header: Analytics                 [Account Selector] │
├─────────────────────────────────────────────────────┤
│ Stat cards row (3 cards):                            │
│   [Monthly Net PnL]  [Winning Days]  [Total Trades]  │
├─────────────────────────────────────────────────────┤
│ Calendar section:                                    │
│   ←  December 2025  →                    [Today]    │
│   Su   Mo   Tu   We   Th   Fr   Sa   │  Week        │
│  ┌────┬────┬────┬────┬────┬────┬────┐ ┌────┐        │
│  │    │    │  1 │  2 │  3 │  4 │  5 │ │ W1 │        │
│  │    │    │    │    │+142│    │    │ │+142│        │
│  └────┴────┴────┴────┴────┴────┴────┘ └────┘        │
│  ... (5–6 rows) ...                                  │
└─────────────────────────────────────────────────────┘
```

### Day Cell States

| State | Background | Text |
|---|---|---|
| Profitable (PnL > 0) | `bg-green-900/40` | `text-green-400` |
| Losing (PnL < 0) | `bg-red-900/40` | `text-red-400` |
| No trades | `bg-muted/20` | muted |
| Outside current month | same + `opacity-30` | — |
| Selected (clicked) | `ring-2 ring-blue-500` | — |

### Drill-Down Sheet (right side)

Opens on day click. Contains:
- Header: selected date + day total PnL (color-coded)
- Table columns: Symbol | Direction | Volume | Entry | Exit | PnL | Duration

Uses existing `Trade` type from `src/types/trading.ts`.

---

## Out of Scope (for this iteration)

- Mobile responsiveness beyond basic legibility
- Hover tooltips (selection + sheet covers this)
- PnL export / CSV download
- Multi-account overlay view

---

## Implementation Order

1. Backend: add date-range filter (`date_from`, `date_to`) to `GET /api/v1/trades`
2. Backend: add `GET /api/v1/analytics/daily` endpoint
3. Frontend: move `AccountSelector` into `app-header.tsx`
4. Frontend: add Analytics page + sidebar link
5. Frontend: build `calendar-grid.tsx` + `day-cell.tsx` + `week-summary-cell.tsx`
6. Frontend: build `pnl-calendar.tsx` container with data fetching
7. Frontend: build `trade-drill-down.tsx` Sheet
8. Frontend: stat cards row (monthly summary)
9. Polish: hover states, empty states, color tuning
