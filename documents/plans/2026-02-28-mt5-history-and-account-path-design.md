# MT5 Trade History & Per-Account Terminal Path

**Date:** 2026-02-28
**Status:** Approved

## Problem

1. `Account` model has no `mt5_path` field — all accounts share a single global `MT5_PATH` from `.env`, which breaks multi-terminal setups (each MT5 account needs its own `terminal64.exe` copy).
2. `MT5Bridge` has no history methods — closed trade data from MT5 cannot be fetched, blocking analytics, AI context, and DB reconciliation.

## Chosen Approach: Option B — Bridge + HistorySync Service

History methods on `MT5Bridge` (raw I/O only), `services/history_sync.py` owns all business logic. This follows the existing service-layer convention and avoids duplicating sync logic across callers.

---

## Section 1: Data Model — `Account.mt5_path`

### `db/models.py`
Add one column to `Account`:
```python
mt5_path: Mapped[str] = mapped_column(String(500), default="")
```
Empty string = fall back to `settings.mt5_path` global default.

### Alembic migration
`alembic/versions/xxxx_add_mt5_path_to_accounts.py`
Single `ALTER TABLE accounts ADD COLUMN mt5_path VARCHAR(500) NOT NULL DEFAULT ''`.

### `api/routes/accounts.py`
- `AccountCreate`: add `mt5_path: str = ""`
- `AccountUpdate`: add `mt5_path: str | None = None`
- `AccountResponse`: add `mt5_path: str`
- `_to_response()`: include `mt5_path`
- `create_account`: set `account.mt5_path = payload.mt5_path`
- `update_account`: apply `mt5_path` if provided
- All `AccountCredentials` construction: replace `path=settings.mt5_path` → `path=account.mt5_path or settings.mt5_path`

---

## Section 2: MT5Bridge History Methods

Add to `mt5/bridge.py`:

```python
async def history_deals_get(self, date_from: datetime, date_to: datetime) -> list[dict]:
    """Fetch all closed deals in [date_from, date_to]. Each deal is one fill leg."""

async def history_orders_get(self, date_from: datetime, date_to: datetime) -> list[dict]:
    """Fetch all historical orders in [date_from, date_to]."""
```

Both follow the existing `_run()` + `._asdict()` pattern. Returns `[]` on no data.

**Key MT5 deal fields used by sync:**

| Field | Description |
|---|---|
| `position_id` | Groups the IN + OUT deal pair for one trade |
| `type` | 0 = buy leg, 1 = sell leg |
| `entry` | 0 = DEAL_ENTRY_IN, 1 = DEAL_ENTRY_OUT |
| `symbol` | Trading instrument |
| `volume` | Lot size |
| `price` | Execution price |
| `profit` | Realised P&L (on OUT deal) |
| `commission` | Broker commission |
| `swap` | Overnight swap |
| `time` | Unix timestamp of execution |
| `ticket` | Unique deal ticket |

---

## Section 3: `services/history_sync.py`

`HistoryService` — four methods, all `async`:

### `get_raw_deals(account, days, db) -> list[dict]`
- Decrypts password, builds `AccountCredentials` with `account.mt5_path or settings.mt5_path`
- Opens `MT5Bridge`, calls `history_deals_get(now - timedelta(days=days), now)`
- Returns raw deal dicts. Raises `RuntimeError` / `ConnectionError` on MT5 failure.

### `sync_to_db(account, days, db) -> dict`
- Calls `get_raw_deals`
- Filters to OUT deals only (`entry == 1`) — each represents one closed position
- For each OUT deal, looks up the matching IN deal by `position_id`
- Checks if `Trade` with `ticket=position_id` already exists for `account_id` (upsert guard)
- Creates new `Trade` rows for unseen tickets:
  - `ticket` = `position_id`
  - `direction` = "BUY" if IN deal type == 0 else "SELL"
  - `entry_price` = IN deal price, `close_price` = OUT deal price
  - `profit` = OUT deal profit + commission + swap
  - `opened_at` / `closed_at` from deal timestamps (timezone-aware UTC)
  - `source` = "manual", `is_paper_trade` = False
- Returns `{"imported": N, "total_fetched": M}`

### `get_performance_summary(deals) -> dict`
Pure function (no I/O). Computes from OUT deals:
- `win_rate`, `total_pnl`, `profit_factor`, `avg_rr`, `trade_count`

### `format_for_llm(deals, limit=10) -> str`
Pure function. Returns compact text block of the N most recent closed trades for LLM prompt injection. Example:
```
Recent closed trades (last 10):
  - EURUSD BUY 0.1 lot | entry=1.0820 close=1.0850 profit=+30.00 | 2026-02-27
  - GBPUSD SELL 0.1 lot | entry=1.2600 close=1.2550 profit=+50.00 | 2026-02-26
```

---

## Section 4: API Endpoints

Add to `api/routes/accounts.py`:

### `GET /api/v1/accounts/{id}/history?days=90`
- Calls `HistoryService.get_raw_deals()`
- Returns raw deal list for dashboard charts / analytics
- Errors: 404, 502, 503 (same pattern as `/info`)

### `POST /api/v1/accounts/{id}/history/sync`
- Calls `HistoryService.sync_to_db()`
- Returns `{"imported": N, "total_fetched": M}`
- Errors: 404, 502, 503

### AI context wiring in `analyze_account`
- After fetching market data, call `HistoryService.get_raw_deals(days=30)`
- Pass `HistoryService.format_for_llm(deals)` as new `trade_history_context` param to `analyze_market()`
- Add `trade_history_context: str | None = None` parameter to `orchestrator.analyze_market()`
- Inject into `_HUMAN` prompt template as `{history_section}`

---

## Files Changed

| File | Change |
|---|---|
| `db/models.py` | Add `mt5_path` column to `Account` |
| `alembic/versions/xxxx_add_mt5_path_to_accounts.py` | New migration |
| `mt5/bridge.py` | Add `history_deals_get`, `history_orders_get` |
| `services/history_sync.py` | New file — `HistoryService` |
| `api/routes/accounts.py` | Schema updates + 2 new endpoints + AI context wiring |
| `ai/orchestrator.py` | Add `trade_history_context` param + `{history_section}` in prompt |

## Out of Scope
- Frontend UI for history (separate task)
- Alembic initialization (`alembic init`) if not yet done — check first
- Automatic startup sync (can be added later as a background task)
