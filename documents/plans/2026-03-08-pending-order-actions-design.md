# Design: Pending Order Action Types

**Date:** 2026-03-08
**Status:** Approved

## Problem

The system only supports `BUY` and `SELL` (market orders). Strategies — especially pattern-based ones like HarmonicStrategy — generate a precise entry price that should be placed as a pending order (limit or stop), not executed at the current market price. Without pending order support, slippage degrades entry quality and the PRZ precision from harmonic pattern detection is wasted.

## Decision: Expand `action` field (Approach A)

The `action` field in `StrategyResult`, `TradingSignal`, and all TypeScript types expands from 3 values to 7:

```
"BUY"         — market buy (immediate execution at current ask)
"SELL"         — market sell (immediate execution at current bid)
"BUY_LIMIT"   — buy if price drops TO entry_price (entry must be below current)
"SELL_LIMIT"  — sell if price rises TO entry_price (entry must be above current)
"BUY_STOP"    — buy on upside breakout (entry must be above current price)
"SELL_STOP"   — sell on downside breakout (entry must be below current price)
"HOLD"         — no signal
```

Two helpers added to `base_strategy.py`:
- `is_market_order(action: str) -> bool` — True for BUY/SELL
- `direction_from_action(action: str) -> str` — strips _LIMIT/_STOP suffix → "BUY" | "SELL" | "HOLD"

The existing `entry` field serves as the pending trigger price. No new fields needed.

## DB Choices

- **Pending order lifecycle:** Full (pending → filled / cancelled / expired)
- **Expiry policy:** GTC (Good Till Cancelled) — `ORDER_TIME_GTC`
- **Storage:** Same `trades` table, two new columns

## Files Changed

| File | Change |
|------|--------|
| `backend/strategies/base_strategy.py` | Expand `StrategyResult.action` literal; add helpers |
| `backend/ai/orchestrator.py` | Expand `TradingSignal` validator; update `_EXECUTION_SYSTEM` prompt; update `_normalize_raw` |
| `backend/mt5/executor.py` | New MT5 constants; expand `OrderRequest.action` validator; branch `place_order()` for pending vs market |
| `backend/db/models.py` | Add `order_type` + `order_status` columns to `Trade` |
| `backend/alembic/versions/<new>.py` | Migration: add `order_type` (default "market") + `order_status` (default "filled") |
| `backend/strategies/harmonic/prz_calculator.py` | Return `BUY_LIMIT`/`SELL_LIMIT` instead of `BUY`/`SELL` |
| `frontend/src/types/trading.ts` | Expand action/signal union types; add `order_type?` + `order_status?` to `Trade` |

## Section 1 — Signal Layer

### `StrategyResult` (`base_strategy.py`)

```python
@dataclass
class StrategyResult:
    action: Literal["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "HOLD"]
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    confidence: float
    rationale: str
    timeframe: str
    pattern_name: str | None = None
    pattern_metadata: dict | None = None
    llm_result: object | None = None


def is_market_order(action: str) -> bool:
    return action in {"BUY", "SELL"}


def direction_from_action(action: str) -> str:
    """Return underlying direction: BUY_LIMIT → BUY, SELL_STOP → SELL, HOLD → HOLD."""
    if action.startswith("BUY"):
        return "BUY"
    if action.startswith("SELL"):
        return "SELL"
    return "HOLD"
```

### `MultiAgentStrategy` consensus fix (`base_strategy.py:226`)

```python
# Before
if llm_result.signal.action != rule_result.action:

# After — compare underlying direction, not execution type
if direction_from_action(llm_result.signal.action) != direction_from_action(rule_result.action):
```

## Section 2 — LLM Orchestrator (`orchestrator.py`)

### `TradingSignal` validator

```python
VALID_ACTIONS = {"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "HOLD"}

@field_validator("action")
@classmethod
def validate_action(cls, v: str) -> str:
    if v.upper() not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {VALID_ACTIONS}")
    return v.upper()
```

### `_EXECUTION_SYSTEM` prompt additions

```
"action": "BUY | SELL | BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | HOLD"

Order type guidance:
- BUY / SELL: market order — use when price is already at your optimal entry level.
- BUY_LIMIT: pending buy below current price — expect retracement to 'entry' then up.
- SELL_LIMIT: pending sell above current price — expect retracement to 'entry' then down.
- BUY_STOP: pending buy above current price — buy on upside breakout through 'entry'.
- SELL_STOP: pending sell below current price — sell on downside breakdown through 'entry'.
- HOLD: no trade.
```

### `_normalize_raw` update

Expand the set of valid actions in the normalization step to match the validator.

## Section 3 — Executor Layer (`executor.py`)

### New MT5 constants

```python
try:
    import MetaTrader5 as mt5
    _ORDER_TYPE_BUY        = mt5.ORDER_TYPE_BUY         # 0
    _ORDER_TYPE_SELL       = mt5.ORDER_TYPE_SELL        # 1
    _ORDER_TYPE_BUY_LIMIT  = mt5.ORDER_TYPE_BUY_LIMIT   # 2
    _ORDER_TYPE_SELL_LIMIT = mt5.ORDER_TYPE_SELL_LIMIT  # 3
    _ORDER_TYPE_BUY_STOP   = mt5.ORDER_TYPE_BUY_STOP    # 4
    _ORDER_TYPE_SELL_STOP  = mt5.ORDER_TYPE_SELL_STOP   # 5
    _TRADE_ACTION_DEAL     = 1   # mt5.TRADE_ACTION_DEAL
    _TRADE_ACTION_PENDING  = mt5.TRADE_ACTION_PENDING   # 5
    _ORDER_FILLING_IOC     = mt5.ORDER_FILLING_IOC
except ImportError:
    _ORDER_TYPE_BUY = 0; _ORDER_TYPE_SELL = 1
    _ORDER_TYPE_BUY_LIMIT = 2; _ORDER_TYPE_SELL_LIMIT = 3
    _ORDER_TYPE_BUY_STOP = 4; _ORDER_TYPE_SELL_STOP = 5
    _TRADE_ACTION_DEAL = 1; _TRADE_ACTION_PENDING = 5
    _ORDER_FILLING_IOC = 1
```

### `OrderRequest` changes

```python
class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    action: str = Field(..., description="BUY | SELL | BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP")
    volume: float = Field(..., gt=0.0)
    entry_price: float = Field(..., gt=0.0)
    stop_loss: float = Field(..., gt=0.0)
    take_profit: float = Field(..., gt=0.0)
    comment: str = Field(default="AI-Trade", max_length=64)
    deviation: int = Field(default=20, ge=0)  # used only for market orders

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        valid = {"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
        if v.upper() not in valid:
            raise ValueError(f"action must be one of {valid}")
        return v.upper()
```

### `place_order()` branching

```python
_PENDING_ACTIONS = {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
_ORDER_TYPE_MAP = {
    "BUY":        _ORDER_TYPE_BUY,
    "SELL":       _ORDER_TYPE_SELL,
    "BUY_LIMIT":  _ORDER_TYPE_BUY_LIMIT,
    "SELL_LIMIT": _ORDER_TYPE_SELL_LIMIT,
    "BUY_STOP":   _ORDER_TYPE_BUY_STOP,
    "SELL_STOP":  _ORDER_TYPE_SELL_STOP,
}

is_pending = request.action in _PENDING_ACTIONS
mt5_action = _TRADE_ACTION_PENDING if is_pending else _TRADE_ACTION_DEAL
order_type = _ORDER_TYPE_MAP[request.action]

mt5_request = {
    "action": mt5_action,
    "symbol": request.symbol,
    "volume": request.volume,
    "type": order_type,
    "price": request.entry_price,
    "sl": request.stop_loss,
    "tp": request.take_profit,
    "magic": 20250101,
    "comment": request.comment,
    "type_time": 0,   # ORDER_TIME_GTC
    "type_filling": filling_mode,
}
if not is_pending:
    mt5_request["deviation"] = request.deviation
```

## Section 4 — Database Schema

### Migration (new Alembic version)

Two columns added to `trades`:

```python
# Alembic upgrade
op.add_column("trades", sa.Column("order_type",   sa.String(6),  nullable=False, server_default="market"))
op.add_column("trades", sa.Column("order_status", sa.String(9),  nullable=False, server_default="filled"))
```

Existing rows default to `order_type="market"`, `order_status="filled"` — correct for all historical market-order trades.

### SQLAlchemy model additions (`models.py`)

```python
order_type:   Mapped[str] = mapped_column(String(6),  default="market")  # market | limit | stop
order_status: Mapped[str] = mapped_column(String(9),  default="filled")  # pending | filled | cancelled | expired
```

`direction` stays `VARCHAR(4)` as `"BUY"` | `"SELL"` (underlying direction).

### `ai_journal.signal` column

Already `VARCHAR(10)` — "BUY_LIMIT" (9 chars) fits. No schema change needed.

## Section 5 — Frontend Types (`trading.ts`)

```typescript
// Shared type
type OrderAction = "BUY" | "SELL" | "BUY_LIMIT" | "SELL_LIMIT" | "BUY_STOP" | "SELL_STOP" | "HOLD";

// Trade interface additions
export interface Trade {
  // ...existing...
  direction: "BUY" | "SELL";            // underlying direction (unchanged)
  order_type?: "market" | "limit" | "stop";
  order_status?: "pending" | "filled" | "cancelled" | "expired";
}

// AISignal, AnalyzeResult, StrategyRun, PipelineRunSummary
// signal / action / final_action fields → use OrderAction
```

## Section 6 — Harmonic Strategy Bonus Fix (`prz_calculator.py`)

PRZ entries should use `BUY_LIMIT`/`SELL_LIMIT` since the strategy waits for price to reach the D point:

```python
# Before
action = "BUY" if is_bullish else "SELL"

# After
action = "BUY_LIMIT" if is_bullish else "SELL_LIMIT"
```

## Implementation Order

1. `base_strategy.py` — helpers + StrategyResult literal
2. `orchestrator.py` — TradingSignal validator + prompt + normalize
3. `executor.py` — constants + OrderRequest + place_order branch
4. `db/models.py` — new columns
5. Alembic migration
6. `prz_calculator.py` — harmonic action fix
7. `frontend/src/types/trading.ts` — TypeScript union types
