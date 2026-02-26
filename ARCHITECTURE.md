# Architecture

## Module Responsibilities

| Module | Owns | Must Never |
|--------|------|------------|
| `mt5/bridge.py` | MT5 connection, auth, raw API | Business logic, DB access |
| `mt5/executor.py` | Order placement, modification, close | Direct `MetaTrader5` import |
| `ai/orchestrator.py` | LangChain chain, LLM calls, signal parsing | HTTP routes, DB writes |
| `ai/vision.py` | Chart screenshot → LLM Vision analysis | Indicator calculation |
| `api/routes/` | Request validation, response shaping | DB queries, MT5/LLM calls |
| `services/` | Business rules, trade validation, analytics | HTTP concerns, raw MT5 |
| `db/models.py` | ORM schema definitions | Query logic |
| `db/postgres.py` | Session factory, engine, `init_db` | Model definitions |
| `core/config.py` | Settings via pydantic-settings | Side effects on import |
| `core/security.py` | Fernet encrypt/decrypt | Key storage |

## Data Flow

```
MT5 Terminal (price feed)
        │
        ▼
mt5/data_feed.py ──────────────► db/questdb.py
        │                         (OHLCV, ticks)
        │
        ▼
ai/orchestrator.py
   ├── Structured: OHLCV + RSI/MA from QuestDB
   └── Vision: chart screenshot via ai/vision.py
        │
        │ TradingSignal (action, entry, sl, tp, confidence, rationale)
        ▼
services/trade_validator.py
   ├── services/kill_switch.is_active() ──► HALT if true
   └── risk checks (margin, max lot, drawdown limit)
        │
        ▼
mt5/executor.py ──► MT5 Terminal (place order)
        │
        ▼
db/postgres.py  (Trade + AIJournal rows)
        │
        ▼
api/routes/ws.py ──► WebSocket broadcast ──► Next.js Dashboard
```

## Database Schema

**PostgreSQL (relational)**
- `accounts` — broker credentials (password Fernet-encrypted), account metadata
- `trades` — every order opened/closed with full price details
- `ai_journal` — LLM rationale, confidence, indicator snapshot per trade
- `kill_switch_log` — activation/deactivation audit trail

**QuestDB (time-series)**
- `ticks_{symbol}` — raw bid/ask tick stream
- `ohlcv_{symbol}_{timeframe}` — candlestick data (M1 to D1)
- `equity_snapshots` — balance/equity/margin per account, sampled periodically

## WebSocket Protocol

Endpoint: `ws://localhost:8000/ws/dashboard/{account_id}`

Server → Client events:
```json
{ "event": "equity_update",        "data": { "equity": 10250.0, "balance": 10000.0, "margin": 150.0 } }
{ "event": "trade_opened",         "data": { "ticket": 12345, "symbol": "XAUUSD", "direction": "BUY" } }
{ "event": "trade_closed",         "data": { "ticket": 12345, "profit": 42.5 } }
{ "event": "ai_signal",            "data": { "symbol": "EURUSD", "action": "SELL", "confidence": 0.82 } }
{ "event": "kill_switch_triggered","data": { "reason": "Max drawdown exceeded" } }
```

## AI Signal Pipeline

1. Fetch last N candles from QuestDB for symbol + timeframe
2. Compute indicators (RSI, EMA20/50/200, ATR) in Python
3. Optionally capture chart screenshot via `ai/vision.py`
4. Build LangChain prompt with structured data + optional vision message
5. Parse LLM response to `TradingSignal` Pydantic model (strict validation)
6. If `confidence < threshold` → force HOLD regardless of action
7. Pass signal to `services/trade_validator.py` for final risk check

## Design Rules

1. **Kill switch is a hard gate** — no exceptions, no bypass, checked in `executor.py` before every order.
2. **MT5 is synchronous** — all `MetaTrader5.*` calls must use `asyncio.run_in_executor`. Never call them directly in an `async def`.
3. **LLM is advisor, Python is enforcer** — the AI produces a signal; Python validates risk limits, margin, and lot size before execution.
4. **Confidence threshold** — default 0.7; signals below threshold are silently converted to HOLD.
5. **Stateless connections** — each trading cycle re-authenticates to MT5 (no persistent connection state in memory).
6. **Account isolation** — each `MT5Bridge` instance is scoped to one account login. Multi-account runs use separate bridge instances.
7. **Vision is optional** — the system must function without chart screenshots; vision enhances but is not required.
8. **Time-series writes are fire-and-forget** — QuestDB inserts use `asyncio.create_task` and must not block the trading cycle.
