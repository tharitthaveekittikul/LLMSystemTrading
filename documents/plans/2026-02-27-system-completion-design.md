# System Completion Design
**Date:** 2026-02-27
**Scope:** Alembic migrations, AI trading loop, Redis utilities, frontend pages

---

## 1. Alembic Migrations

**Location:** `/backend/alembic/`

**Setup:**
- `alembic init alembic` in `/backend`
- `env.py`: import `db.postgres.Base.metadata` and read `DATABASE_URL` from `core.config.settings`

**Schema change (prerequisite):**
- `AIJournal.trade_id` must become nullable — HOLD signals produce no trade, so we cannot require a linked trade row. Change `Mapped[int]` to `Mapped[int | None]` in `db/models.py`.

**Migrations:**
1. `initial_schema` — creates all 4 tables: `accounts`, `trades`, `ai_journal`, `kill_switch_log`
2. `nullable_trade_id` — alters `ai_journal.trade_id` to `NULL`-allowed

---

## 2. AI Trading Loop

### New service: `services/ai_trading.py`

Class: `AITradingService`
Method: `analyze_and_trade(account_id, symbol, timeframe, confidence_threshold, db)`

**Pipeline:**
1. Load account credentials from DB → decrypt password with Fernet
2. Redis rate limit check: key `llm_rate:{account_id}`, max 10 calls/60s — raise HTTP 429 if exceeded
3. Redis OHLCV cache: key `ohlcv:{account_id}:{symbol}:{timeframe}`
   - Cache hit → deserialize JSON
   - Cache miss → fetch from MT5Bridge → serialize + store (TTL: M15=60s, H1=300s, D1=1800s)
4. Call `orchestrator.generate_signal(symbol, candles, timeframe)` → `TradingSignal`
5. Save `AIJournal` row (`trade_id=None`)
6. Broadcast `ai_signal` WebSocket event (account_id)
7. If `action != HOLD` AND `confidence >= threshold` AND kill switch is off:
   - Build `OrderRequest(symbol, direction=action, volume=account.max_lot_size, entry=signal.entry, sl=signal.stop_loss, tp=signal.take_profit)`
   - `MT5Executor(bridge).place_order(request)` → `OrderResult`
   - If success: persist `Trade` row → update `AIJournal.trade_id` → broadcast `trade_opened`
8. Return `AnalysisResult(signal, order_placed, ticket)`

### New route

`POST /api/v1/accounts/{id}/analyze`

**Request body:**
```json
{ "symbol": "EURUSD", "timeframe": "M15", "confidence_threshold": 0.7 }
```

**Response:**
```json
{
  "action": "BUY",
  "entry": 1.0850,
  "stop_loss": 1.0800,
  "take_profit": 1.0950,
  "confidence": 0.82,
  "rationale": "...",
  "timeframe": "M15",
  "order_placed": true,
  "ticket": 12345678
}
```

**Errors:** 429 rate limited, 503 MT5 unavailable, 423 kill switch active (signal saved, order skipped)

---

## 3. Redis Utilities

Add to `db/redis.py`:

```python
async def check_llm_rate_limit(account_id: int, max_calls: int = 10, window_seconds: int = 60) -> bool:
    """Returns True if call is allowed; False if rate limit exceeded. Uses INCR + EXPIRE."""

async def get_candle_cache(account_id: int, symbol: str, timeframe: str) -> list | None:
    """Returns parsed candle list or None on cache miss."""

async def set_candle_cache(account_id: int, symbol: str, timeframe: str, candles: list, ttl_seconds: int) -> None:
    """Stores candles as JSON string with TTL."""
```

TTL by timeframe: M1/M5=30s, M15=60s, H1=300s, H4=600s, D1=1800s

---

## 4. Frontend Pages

Sidebar already defines all routes. Three new pages in `frontend/src/app/`:

### `/trades` — Trade History

- Filterable table: account selector, date range picker, open/closed toggle
- Columns: ticket, symbol, direction badge, volume, entry, SL/TP, close price, P&L, opened/closed timestamps, source badge
- Calls `GET /api/v1/trades?account_id=&date_from=&date_to=&open_only=`
- Empty state when no trades

### `/signals` — AI Signal Journal

- Card feed sorted by created_at desc
- Each card: action badge (BUY=green/SELL=red/HOLD=gray), symbol, timeframe, confidence progress bar, rationale text, linked trade ticket (if placed)
- Calls `GET /api/v1/signals` (new backend route reading `ai_journal`)
- Manual trigger form: select account → symbol input → timeframe select → confidence slider → "Analyze" button → calls `POST /api/v1/accounts/{id}/analyze`

### `/kill-switch` — Kill Switch Control

- Large toggle button (red = active, green = inactive) with status label
- Reason textarea (required to activate)
- Event log table: action, reason, triggered_by, timestamp
- Calls `GET /api/v1/kill-switch` (status), `POST /api/v1/kill-switch/activate`, `POST /api/v1/kill-switch/deactivate`

---

## Data Flow Summary

```
POST /analyze
  → AITradingService
    → Redis rate limit check
    → Redis OHLCV cache (or MT5Bridge if miss)
    → orchestrator.generate_signal()
    → save AIJournal (trade_id=None)
    → broadcast ai_signal
    → [if BUY/SELL + confident + kill switch off]
      → MT5Executor.place_order()
      → save Trade
      → update AIJournal.trade_id
      → broadcast trade_opened
  → return AnalysisResult
```
