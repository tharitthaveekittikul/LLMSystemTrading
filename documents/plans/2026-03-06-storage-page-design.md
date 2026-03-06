# Storage Service Page — Design Document

**Date:** 2026-03-06
**Status:** Approved
**Scope:** Full-stack — new backend route module + new frontend page

---

## Overview

A Storage Admin Panel that lets you monitor and manage all three storage systems
(PostgreSQL, QuestDB, Redis) from within the trading dashboard. Provides both
read-only observability (disk sizes, row counts, connection info) and targeted
management operations (purge by date, truncate, drop table, flush Redis).

Approach chosen: **Embedded Stats + Targeted Operations** — purpose-built endpoints
per storage system, no generic SQL runner, safety enforced server-side.

---

## Architecture

### Backend

**New file:** `backend/api/routes/storage.py`
Registered in `main.py` with prefix `/api/v1/storage`.

No new service layer needed — storage introspection queries are thin enough to
live in the route module. Uses the existing `AsyncSession` dependency for
PostgreSQL, the existing `QuestDBClient` for QuestDB, and a new lazy `redis.asyncio`
client initialized on first request.

### Frontend

**New page:** `frontend/src/app/storage/page.tsx`
**New components:** `frontend/src/components/storage/`
**New types:** `frontend/src/types/storage.ts`
**API additions:** `storageApi` object added to `frontend/src/lib/api.ts`

Data fetching: plain `useEffect` + `useState` + `apiRequest` — consistent with
all existing pages. No new global Zustand store (storage data is local state).

---

## Backend API Endpoints

### PostgreSQL

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/storage/postgres/overview` | DB size, version, active connection count |
| `GET` | `/api/v1/storage/postgres/tables` | All tables: row count, total size, index size, last vacuum |
| `GET` | `/api/v1/storage/postgres/tables/{name}/rows` | Paginated row browser (`?page=1&limit=50`) |
| `DELETE` | `/api/v1/storage/postgres/tables/{name}/purge` | Delete rows older than N days (`?older_than_days=90`) |
| `DELETE` | `/api/v1/storage/postgres/tables/{name}/truncate` | Wipe entire table |

**Table classification (hardcoded server-side):**

Protected (read + browse only — no truncate or purge):
- `accounts`, `trades`, `strategies`, `account_strategies`
- `ai_journal`, `llm_provider_configs`, `task_llm_assignments`
- `hmm_model_registry`, `alembic_version`

Purgeable (support purge-by-date + truncate):
- `pipeline_runs` — purge column: `created_at`
- `pipeline_steps` — purge column: `created_at` (via join on `run_id`)
- `backtest_runs` — purge column: `created_at`
- `backtest_trades` — purge column: `entry_time`
- `kill_switch_log` — purge column: `created_at`

### QuestDB

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/storage/questdb/tables` | All tables: row count, column count, partition count |
| `GET` | `/api/v1/storage/questdb/tables/{name}/rows` | Paginated rows (`?page=1&limit=50`) |
| `DELETE` | `/api/v1/storage/questdb/tables/{name}` | `DROP TABLE` — permanent |

Implementation: QuestDB REST API at `http://questdb:9000/exec`. Table list via
`SHOW TABLES`, stats via `SELECT count() FROM {table}`, drop via `DROP TABLE {table}`.
Table name validated against live `SHOW TABLES` result before any mutation.

### Redis

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/storage/redis/info` | Memory used, key count, uptime, version, hit/miss ratio |
| `DELETE` | `/api/v1/storage/redis/flush` | `FLUSHDB` (current DB only, not FLUSHALL) |

Implementation: `redis.asyncio` client, lazy-initialized on first request.
Gracefully returns `{"status": "unreachable"}` if Redis is down — does not crash.

---

## Frontend Components

```
frontend/src/app/storage/
└── page.tsx                          ← StoragePage (tab state, data fetching)

frontend/src/components/storage/
├── storage-overview-cards.tsx        ← 3 system status cards (always visible)
├── postgres-panel.tsx                ← table list + purge/truncate actions
├── questdb-panel.tsx                 ← table list + drop actions
├── redis-panel.tsx                   ← info metrics grid + flush button
├── table-browser-sheet.tsx           ← side sheet: column headers + paginated rows
└── confirm-destructive-dialog.tsx    ← shared confirmation dialog (type-to-confirm)

frontend/src/types/storage.ts         ← TS types for all API responses
```

### Overview Cards (above tabs)

Three cards always visible at the top of the page:

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ PostgreSQL    ●  │  │ QuestDB       ●  │  │ Redis         ●  │
│ 14.2 MB          │  │ 3 tables         │  │ 0 keys           │
│ 13 tables        │  │ 48 312 rows      │  │ 512 KB used      │
│ 12 connections   │  │ v8.1.2           │  │ v7.0.15          │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

Status dot: green = reachable, red = unreachable.

### PostgreSQL Tab

Table list with columns: Name | Rows | Total Size | Index Size | Last Vacuum | Actions

Tables split into two visual groups:
1. **Purgeable** — show `[Purge ▾]` dropdown (30/60/90/Custom days) + `[Truncate]` button
2. **Protected** — show `[Browse]` only, no mutation buttons

Clicking any table name opens the Table Browser Sheet.

### QuestDB Tab

Table list with columns: Name | Rows | Columns | Partitions | Actions

Each row has `[Browse]` + `[Drop]` button. No protected tables (all QuestDB
tables are time-series that can be recreated by the app on next startup).

### Redis Tab

Stat grid: Used Memory | Total Keys | Uptime | Version | Hit Ratio | Miss Ratio

Single `[Flush DB]` button at the bottom. If Redis is unreachable, all stats
show "—" and the flush button is disabled with tooltip "Redis unreachable".

### Table Browser Sheet (shared)

Opens as a right-side sheet (`Sheet` from shadcn/ui). Shows:
- Table name + system badge (PostgreSQL / QuestDB)
- Column headers derived from first row keys
- Paginated rows (50 per page) with Prev / Next controls
- Row count summary: "Showing 1–50 of 4 821 rows"

### Confirmation Dialog (shared)

Used for: Truncate, Drop QuestDB table, Redis Flush, Purge.

```
⚠ Truncate "pipeline_steps"?
This will permanently delete 62 134 rows. This cannot be undone.

Type the table name to confirm:
[ pipeline_steps        ]

                    [Cancel]  [Truncate]  ← enabled only when text matches
```

For Redis Flush: user types `FLUSH` instead of a table name.
For Purge: shows rows-to-delete count estimate + selected date threshold.

### Sidebar

Add "Storage" nav item (`Database` icon from lucide-react) between
"Pipeline Logs" and "Analytics" in `app-sidebar.tsx`.

---

## Data Flow

### Page Load

```
StoragePage mounts
  → parallel fetch: postgres/overview + questdb/tables + redis/info
  → overview cards render with live data
  → active tab (default: PostgreSQL) fetches its table list
  → other tabs fetch lazily on first click
```

### Destructive Action

```
user clicks [Truncate] / [Drop] / [Flush]
  → ConfirmDestructiveDialog opens
  → user types confirmation text
  → [Confirm] button enables
  → DELETE request fires
  → success: toast "Truncated pipeline_steps (62 134 rows deleted)"
           + refetch that storage system's table list
           + refetch overview cards
  → error: toast error, dialog stays open
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| QuestDB unreachable | Card shows red dot + "Unreachable"; QuestDB tab disabled |
| Redis unreachable | Card shows red dot; Redis tab shows info note, flush disabled |
| PostgreSQL unreachable | Full page error state (app cannot function without PG) |
| Protected table mutate attempt | Backend returns 403; frontend never shows those buttons |
| Unknown table in URL param | Backend returns 404 |
| Concurrent delete race | Backend re-validates table existence before executing |

---

## Safety Rules (enforced server-side)

1. Protected table list is hardcoded in `storage.py` — not derived from any
   client-supplied input
2. Truncate/purge table name is validated against the hardcoded purgeable list
3. QuestDB DROP validates table name against live `SHOW TABLES` result
4. QuestDB queries use parameterized REST calls — no string concatenation of
   user input into SQL
5. Redis `FLUSHDB` only — never `FLUSHALL`
6. Purge `older_than_days` is cast to `int` with a minimum of 1 day

---

## Files to Create / Modify

### Create (backend)
- `backend/api/routes/storage.py`

### Modify (backend)
- `backend/main.py` — register storage router

### Create (frontend)
- `frontend/src/app/storage/page.tsx`
- `frontend/src/components/storage/storage-overview-cards.tsx`
- `frontend/src/components/storage/postgres-panel.tsx`
- `frontend/src/components/storage/questdb-panel.tsx`
- `frontend/src/components/storage/redis-panel.tsx`
- `frontend/src/components/storage/table-browser-sheet.tsx`
- `frontend/src/components/storage/confirm-destructive-dialog.tsx`
- `frontend/src/types/storage.ts`

### Modify (frontend)
- `frontend/src/lib/api.ts` — add `storageApi`
- `frontend/src/components/app-sidebar.tsx` — add Storage nav item
