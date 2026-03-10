# Risk Manager — Design Spec
**Date:** 2026-03-10
**Scope:** Global risk rules with per-rule toggles, rate limiting, and hedging support
**Status:** Approved

---

## Problem Statement

The existing risk manager has two hard-wired checks (drawdown, position limit) with no way to toggle them off or configure them from the UI. There is no rate limiting per symbol and no hedging support. All risk config lives in `.env` only.

---

## Goals

1. Make every risk rule independently toggleable (on/off)
2. Add rate limiting: max X positions per symbol per rolling Y hours
3. Allow opposite-side hedging (configurable toggle)
4. Expose all configuration in the Settings page (no more `.env` edits for risk)
5. Default all existing checks to **disabled** for the initial rollout (bypass period)

---

## Non-Goals

- Per-account risk settings (global only for now)
- Real-time risk dashboard / violation history
- Notification/alert on rule breach (kill switch handles drawdown already)

---

## Architecture

### 1. Data Model

**New table: `risk_settings`** — singleton (id = 1)

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | Integer PK | 1 | Singleton row |
| `drawdown_check_enabled` | Boolean | `false` | Bypass by default |
| `max_drawdown_pct` | Float | 10.0 | % drawdown that triggers kill switch |
| `position_limit_enabled` | Boolean | `false` | Bypass by default |
| `max_open_positions` | Integer | 5 | Max concurrent open positions |
| `rate_limit_enabled` | Boolean | `false` | Off by default |
| `rate_limit_max_trades` | Integer | 3 | Max trades per symbol per window |
| `rate_limit_window_hours` | Float | 4.0 | Rolling lookback window in hours |
| `hedging_allowed` | Boolean | `true` | Allow opposite-side positions on same symbol |
| `updated_at` | DateTime | now() | Last updated timestamp |

**Alembic migration:** creates table and seeds default row (id=1).

---

### 2. Backend — Risk Manager (`backend/services/risk_manager.py`)

Rewritten with 4 functions. Settings always passed as a parameter (no DB I/O inside pure functions).

```python
# Pure functions — no I/O
def check_drawdown(equity: float, balance: float, settings: RiskSettings) -> tuple[bool, str]
def check_position_limit(positions: list[dict], settings: RiskSettings) -> tuple[bool, str]
def check_hedging(symbol: str, direction: str, positions: list[dict], settings: RiskSettings) -> tuple[bool, str]

# Async — queries trades table
async def check_rate_limit(symbol: str, settings: RiskSettings, db: AsyncSession) -> tuple[bool, str]
```

**Rule behavior:**

| Rule | Enabled=False | Enabled=True |
|------|---------------|--------------|
| `check_drawdown` | Returns `(False, "")` immediately | Compares `(balance - equity) / balance * 100` against `max_drawdown_pct` |
| `check_position_limit` | Returns `(False, "")` immediately | Counts open positions, rejects if `>= max_open_positions` |
| `check_hedging` | `hedging_allowed=True` → always passes | `hedging_allowed=False` → rejects if opposite-side position already open on symbol |
| `check_rate_limit` | Returns `(False, "")` immediately | Counts `trades` WHERE `symbol=X AND opened_at >= now() - window_hours`; rejects if `>= max_trades` |

**Rate limit query (PostgreSQL):**
```sql
SELECT COUNT(*) FROM trades
WHERE symbol = :symbol
  AND opened_at >= NOW() - INTERVAL ':hours hours'
```
Hedging counts toward the rate limit (no exemption).

---

### 3. Backend — API (`backend/api/routes/settings.py`)

Two new endpoints added to the existing settings router:

```
GET   /settings/risk   → RiskSettings
PATCH /settings/risk   → RiskSettings
```

**Pydantic models:**
```python
class RiskSettings(BaseModel):
    drawdown_check_enabled: bool
    max_drawdown_pct: float
    position_limit_enabled: bool
    max_open_positions: int
    rate_limit_enabled: bool
    rate_limit_max_trades: int
    rate_limit_window_hours: float
    hedging_allowed: bool

class RiskSettingsPatch(BaseModel):
    drawdown_check_enabled: bool | None = None
    max_drawdown_pct: float | None = None
    position_limit_enabled: bool | None = None
    max_open_positions: int | None = None
    rate_limit_enabled: bool | None = None
    rate_limit_max_trades: int | None = None
    rate_limit_window_hours: float | None = None
    hedging_allowed: bool | None = None
```

---

### 4. Callers Updated

**`mt5/executor.py`**
- Before placing an order, loads `RiskSettings` from DB (one query)
- Calls all 4 checks; any `True` result rejects the order with reason logged

**`services/equity_poller.py`**
- Loads `RiskSettings` from DB each poll cycle
- Calls `check_drawdown` only (existing behavior, now toggleable)

---

### 5. Frontend — Settings Page

**New "Risk Manager" section** in `frontend/src/app/settings/page.tsx` — same card pattern as the existing Maintenance section.

```
┌─ Risk Manager ─────────────────────────────────────────────┐
│                                                             │
│  Drawdown Check              ○──●  [enabled]               │
│  └─ Max drawdown %           [ 10.0 ]                      │
│                                                             │
│  Position Limit              ●──○  [disabled]              │
│  └─ Max open positions       [  5  ]                       │
│                                                             │
│  Rate Limit                  ●──○  [disabled]              │
│  └─ Max trades               [  3  ]  per                  │
│     Window                   [  4  ]  hours (per symbol)   │
│                                                             │
│  Hedging Allowed             ○──●  [enabled]               │
│     Allow opposite-side positions on same symbol           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

- Input fields only visible when rule is enabled (conditional render)
- Auto-saves on any change (debounced 800ms) via `PATCH /settings/risk`
- Loads on mount via `GET /settings/risk`

**New frontend files/changes:**

| File | Change |
|------|--------|
| `frontend/src/types/trading.ts` | Add `RiskSettings` interface |
| `frontend/src/lib/api/settings.ts` | Add `getRisk()` + `patchRisk()` methods |
| `frontend/src/app/settings/page.tsx` | Add `RiskManagerSection` component |

---

## Migration Plan

1. Alembic migration: create `risk_settings` table, seed row with all-disabled defaults
2. Rewrite `risk_manager.py` (pure functions signature-compatible where possible)
3. Update `executor.py` — load settings from DB, call all 4 checks
4. Update `equity_poller.py` — load settings, pass to `check_drawdown`
5. Add `/settings/risk` GET + PATCH to `settings.py`
6. Add `RiskSettings` type + API methods to frontend
7. Add `RiskManagerSection` to settings page

## Validation

- `max_drawdown_pct`: 0 < v ≤ 100
- `max_open_positions`: v ≥ 1
- `rate_limit_max_trades`: v ≥ 1
- `rate_limit_window_hours`: v > 0
