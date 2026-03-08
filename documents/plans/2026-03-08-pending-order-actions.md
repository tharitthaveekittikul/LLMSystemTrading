# Pending Order Action Types Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand the trading system's action vocabulary from BUY/SELL/HOLD to include BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP so strategies and LLMs can request pending orders in MT5.

**Architecture:** The `action` field in `StrategyResult` and `TradingSignal` expands to 7 values. The executor detects market vs pending actions and builds the correct MT5 request (`TRADE_ACTION_DEAL` vs `TRADE_ACTION_PENDING`). The DB tracks pending order state with two new columns on `trades`. HarmonicStrategy gains precision by emitting `BUY_LIMIT`/`SELL_LIMIT`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy + Alembic, MetaTrader5 Python library, Next.js/TypeScript

**Design doc:** `documents/plans/2026-03-08-pending-order-actions-design.md`

---

## Task 1: Expand `StrategyResult` + add action helpers

**Files:**
- Modify: `backend/strategies/base_strategy.py`
- Test: `backend/tests/test_strategy_base.py`

### Step 1: Write failing tests

Add to `backend/tests/test_strategy_base.py`:

```python
def test_direction_from_action_strips_suffix():
    from strategies.base_strategy import direction_from_action
    assert direction_from_action("BUY") == "BUY"
    assert direction_from_action("SELL") == "SELL"
    assert direction_from_action("BUY_LIMIT") == "BUY"
    assert direction_from_action("SELL_LIMIT") == "SELL"
    assert direction_from_action("BUY_STOP") == "BUY"
    assert direction_from_action("SELL_STOP") == "SELL"
    assert direction_from_action("HOLD") == "HOLD"


def test_is_market_order():
    from strategies.base_strategy import is_market_order
    assert is_market_order("BUY") is True
    assert is_market_order("SELL") is True
    assert is_market_order("BUY_LIMIT") is False
    assert is_market_order("SELL_LIMIT") is False
    assert is_market_order("BUY_STOP") is False
    assert is_market_order("SELL_STOP") is False
    assert is_market_order("HOLD") is False


def test_strategy_result_accepts_pending_actions():
    from strategies.base_strategy import StrategyResult
    for action in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
        r = StrategyResult(
            action=action, entry=1.1, stop_loss=1.09,
            take_profit=1.12, confidence=0.8, rationale="test", timeframe="M15",
        )
        assert r.action == action


@pytest.mark.asyncio
async def test_multi_agent_consensus_uses_direction_not_exact_action():
    """Rule says BUY_LIMIT, LLM says BUY — same direction, should execute not HOLD."""
    from unittest.mock import AsyncMock, MagicMock
    from strategies.base_strategy import MultiAgentStrategy, StrategyResult
    from ai.orchestrator import LLMAnalysisResult, LLMRoleResult, TradingSignal

    class TestMultiAgent(MultiAgentStrategy):
        primary_tf = "M15"
        context_tfs = ()
        symbols = ("EURUSD",)

        def check_rule(self, md):
            return StrategyResult(
                action="BUY_LIMIT", entry=1.09, stop_loss=1.08,
                take_profit=1.11, confidence=0.8, rationale="rule", timeframe="M15",
            )

        def system_prompt(self):
            return "test"

        def analytics_schema(self):
            return {}

    def _mock_role():
        return LLMRoleResult(
            content={}, input_tokens=0, output_tokens=0, total_tokens=0,
            model="gpt-4o", provider="openai", duration_ms=100,
        )

    llm_signal = TradingSignal(
        action="BUY", entry=1.09, stop_loss=1.08, take_profit=1.11,
        confidence=0.85, rationale="llm", timeframe="M15",
    )
    llm_analysis = LLMAnalysisResult(
        signal=llm_signal,
        market_analysis=_mock_role(),
        chart_vision=None,
        execution_decision=_mock_role(),
    )

    strategy = TestMultiAgent()
    md = _make_md()

    with patch("ai.orchestrator.analyze_market", new=AsyncMock(return_value=llm_analysis)):
        result = await strategy.run(md)

    # Rule said BUY_LIMIT, LLM said BUY — same direction → use rule's result
    assert result.action == "BUY_LIMIT"
    assert result.entry == 1.09
```

### Step 2: Run tests to verify they fail

```bash
cd backend && uv run pytest tests/test_strategy_base.py::test_direction_from_action_strips_suffix tests/test_strategy_base.py::test_is_market_order tests/test_strategy_base.py::test_strategy_result_accepts_pending_actions -v
```

Expected: FAIL — `direction_from_action` not defined, `StrategyResult.action` literal too narrow

### Step 3: Implement in `backend/strategies/base_strategy.py`

Replace the `StrategyResult` dataclass and add helpers. In `base_strategy.py`:

```python
# Replace the action Literal on StrategyResult:
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


# Add these two helpers after the dataclass (before AbstractStrategy):
def direction_from_action(action: str) -> str:
    """Return underlying direction: BUY_LIMIT -> BUY, SELL_STOP -> SELL, HOLD -> HOLD."""
    if action.startswith("BUY"):
        return "BUY"
    if action.startswith("SELL"):
        return "SELL"
    return "HOLD"


def is_market_order(action: str) -> bool:
    """True only for immediate market execution actions."""
    return action in {"BUY", "SELL"}
```

Fix `MultiAgentStrategy.run()` — replace the consensus check at line ~226:

```python
# OLD:
if llm_result.signal.action != rule_result.action:
    return _HOLD

# NEW:
if direction_from_action(llm_result.signal.action) != direction_from_action(rule_result.action):
    return _HOLD
```

### Step 4: Run tests to verify they pass

```bash
cd backend && uv run pytest tests/test_strategy_base.py -v
```

Expected: all PASS

### Step 5: Commit

```bash
git add backend/strategies/base_strategy.py backend/tests/test_strategy_base.py
git commit -m "feat(strategy): expand StrategyResult action to include pending order types"
```

---

## Task 2: Update `TradingSignal` + orchestrator prompts

**Files:**
- Modify: `backend/ai/orchestrator.py`
- Test: `backend/tests/test_orchestrator.py`

### Step 1: Write failing tests

Add to `backend/tests/test_orchestrator.py`:

```python
def test_trading_signal_accepts_pending_actions():
    from ai.orchestrator import TradingSignal
    for action in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
        sig = TradingSignal(
            action=action, entry=1.085, stop_loss=1.080,
            take_profit=1.095, confidence=0.8, rationale="test", timeframe="M15",
        )
        assert sig.action == action


def test_trading_signal_rejects_unknown_action():
    from pydantic import ValidationError
    from ai.orchestrator import TradingSignal
    with pytest.raises(ValidationError):
        TradingSignal(
            action="LONG", entry=1.085, stop_loss=1.080,
            take_profit=1.095, confidence=0.8, rationale="test", timeframe="M15",
        )


@pytest.mark.asyncio
async def test_analyze_market_returns_pending_action():
    """analyze_market passes through BUY_LIMIT without downgrading it."""
    from unittest.mock import AsyncMock, patch
    from ai.orchestrator import LLMRoleResult, analyze_market

    def _role(content):
        return LLMRoleResult(
            content=content, input_tokens=10, output_tokens=10, total_tokens=20,
            model="gpt-4o", provider="openai", duration_ms=100, raw_text=str(content),
        )

    ma = _role({"trend": "bullish", "trend_strength": 0.8, "key_support": 1.08,
                "key_resistance": 1.09, "volatility": "medium", "context_notes": "ok"})
    ed = _role({"action": "BUY_LIMIT", "entry": 1.082, "stop_loss": 1.078,
                "take_profit": 1.092, "confidence": 0.85, "rationale": "PRZ entry", "timeframe": "M15"})

    with (
        patch("ai.orchestrator._build_llm"),
        patch("ai.orchestrator._run_market_analysis", new=AsyncMock(return_value=ma)),
        patch("ai.orchestrator._run_execution_decision", new=AsyncMock(return_value=ed)),
        patch("ai.orchestrator.settings") as mock_cfg,
    ):
        mock_cfg.llm_confidence_threshold = 0.5
        result = await analyze_market(
            symbol="XAUUSD", timeframe="M15", current_price=1.085,
            indicators={}, ohlcv=[],
        )

    assert result.signal.action == "BUY_LIMIT"
    assert result.signal.entry == 1.082
```

### Step 2: Run tests to verify they fail

```bash
cd backend && uv run pytest tests/test_orchestrator.py::test_trading_signal_accepts_pending_actions tests/test_orchestrator.py::test_trading_signal_rejects_unknown_action tests/test_orchestrator.py::test_analyze_market_returns_pending_action -v
```

Expected: FAIL — validator rejects BUY_LIMIT

### Step 3: Implement in `backend/ai/orchestrator.py`

**3a. Add constant and update validator:**

```python
# After the class definition of TradingSignal, replace the validator:
_VALID_ACTIONS = frozenset({"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "HOLD"})

# Inside TradingSignal:
@field_validator("action")
@classmethod
def validate_action(cls, v: str) -> str:
    if v.upper() not in _VALID_ACTIONS:
        raise ValueError(f"action must be one of {sorted(_VALID_ACTIONS)}")
    return v.upper()
```

**3b. Update `_EXECUTION_SYSTEM` prompt** — replace the action line and add guidance:

```python
_EXECUTION_SYSTEM = """You are a professional forex trader making execution decisions.
Based on the market analysis and position context provided, return ONLY strictly valid JSON.
Use EXACTLY these field names:
{{
  "action": "BUY | SELL | BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | HOLD",
  "entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "confidence": <float 0.0-1.0>,
  "rationale": "<brief 1-2 sentence explanation>",
  "timeframe": "<e.g. M15>"
}}

Order type guidance (IMPORTANT — pick the right action):
- BUY / SELL: market order — use ONLY when price is already at your optimal entry level.
- BUY_LIMIT: pending buy below current price — expect retracement DOWN to 'entry' then reversal up.
- SELL_LIMIT: pending sell above current price — expect retracement UP to 'entry' then reversal down.
- BUY_STOP: pending buy above current price — buy on upside BREAKOUT through 'entry'.
- SELL_STOP: pending sell below current price — sell on downside BREAKDOWN through 'entry'.
- HOLD: no trade opportunity.

Rules:
- Signal BUY or SELL only when multiple indicators confirm the same direction.
- Signal HOLD when uncertain or risk/reward is unfavorable.
- Check open positions before signaling. Avoid doubling same direction unless confidence > 0.90.
- Never open opposing positions simultaneously."""
```

**3c. Update `_normalize_raw` default action** — already sets `out.setdefault("action", "HOLD")`, no change needed.
Update the uppercase normalization step to still just call `.upper()` — already done.

### Step 4: Run tests to verify they pass

```bash
cd backend && uv run pytest tests/test_orchestrator.py -v
```

Expected: all PASS

### Step 5: Commit

```bash
git add backend/ai/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "feat(orchestrator): expand TradingSignal to support pending order action types"
```

---

## Task 3: Update executor — `OrderRequest` + `place_order()` branching

**Files:**
- Modify: `backend/mt5/executor.py`
- Test: `backend/tests/test_auto_trade.py` (add cases there, or create `tests/test_executor.py`)

### Step 1: Write failing tests

Create `backend/tests/test_executor_pending.py`:

```python
"""Tests for executor pending order support."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError


def test_order_request_accepts_pending_actions():
    from mt5.executor import OrderRequest
    for action in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
        req = OrderRequest(
            symbol="XAUUSD", action=action, volume=0.1,
            entry_price=1900.0, stop_loss=1890.0, take_profit=1920.0,
        )
        assert req.action == action


def test_order_request_rejects_hold():
    from mt5.executor import OrderRequest
    with pytest.raises(ValidationError):
        OrderRequest(
            symbol="XAUUSD", action="HOLD", volume=0.1,
            entry_price=1900.0, stop_loss=1890.0, take_profit=1920.0,
        )


def test_order_request_rejects_unknown():
    from mt5.executor import OrderRequest
    with pytest.raises(ValidationError):
        OrderRequest(
            symbol="XAUUSD", action="LONG", volume=0.1,
            entry_price=1900.0, stop_loss=1890.0, take_profit=1920.0,
        )


@pytest.mark.asyncio
async def test_place_order_uses_pending_action_for_buy_limit():
    """BUY_LIMIT sends TRADE_ACTION_PENDING (5) to MT5, not TRADE_ACTION_DEAL (1)."""
    from mt5.executor import MT5Executor, OrderRequest

    mock_bridge = AsyncMock()
    mock_bridge.get_positions = AsyncMock(return_value=[])
    mock_bridge.is_autotrading_enabled = AsyncMock(return_value=True)
    mock_bridge.get_filling_mode = AsyncMock(return_value=1)
    mock_bridge.send_order = AsyncMock(return_value={"retcode": 10009, "order": 12345})

    with (
        patch("mt5.executor.kill_switch_active", return_value=False),
        patch("mt5.executor.exceeds_position_limit", return_value=(False, "")),
    ):
        executor = MT5Executor(mock_bridge)
        req = OrderRequest(
            symbol="XAUUSD", action="BUY_LIMIT", volume=0.1,
            entry_price=1900.0, stop_loss=1890.0, take_profit=1920.0,
        )
        result = await executor.place_order(req)

    assert result.success is True
    sent_request = mock_bridge.send_order.call_args[0][0]
    assert sent_request["action"] == 5   # TRADE_ACTION_PENDING
    assert sent_request["type"] == 2     # ORDER_TYPE_BUY_LIMIT
    assert "deviation" not in sent_request


@pytest.mark.asyncio
async def test_place_order_uses_deal_action_for_buy():
    """BUY sends TRADE_ACTION_DEAL (1) with deviation."""
    from mt5.executor import MT5Executor, OrderRequest

    mock_bridge = AsyncMock()
    mock_bridge.get_positions = AsyncMock(return_value=[])
    mock_bridge.is_autotrading_enabled = AsyncMock(return_value=True)
    mock_bridge.get_filling_mode = AsyncMock(return_value=1)
    mock_bridge.send_order = AsyncMock(return_value={"retcode": 10009, "order": 12346})

    with (
        patch("mt5.executor.kill_switch_active", return_value=False),
        patch("mt5.executor.exceeds_position_limit", return_value=(False, "")),
    ):
        executor = MT5Executor(mock_bridge)
        req = OrderRequest(
            symbol="XAUUSD", action="BUY", volume=0.1,
            entry_price=1905.0, stop_loss=1890.0, take_profit=1925.0,
        )
        result = await executor.place_order(req)

    assert result.success is True
    sent_request = mock_bridge.send_order.call_args[0][0]
    assert sent_request["action"] == 1   # TRADE_ACTION_DEAL
    assert sent_request["type"] == 0     # ORDER_TYPE_BUY
    assert "deviation" in sent_request
```

### Step 2: Run tests to verify they fail

```bash
cd backend && uv run pytest tests/test_executor_pending.py -v
```

Expected: FAIL — `OrderRequest` has no `action` field (it's called `direction`)

### Step 3: Implement in `backend/mt5/executor.py`

**3a. Expand MT5 constants block:**

```python
try:
    import MetaTrader5 as mt5
    _ORDER_TYPE_BUY        = mt5.ORDER_TYPE_BUY
    _ORDER_TYPE_SELL       = mt5.ORDER_TYPE_SELL
    _ORDER_TYPE_BUY_LIMIT  = mt5.ORDER_TYPE_BUY_LIMIT   # 2
    _ORDER_TYPE_SELL_LIMIT = mt5.ORDER_TYPE_SELL_LIMIT  # 3
    _ORDER_TYPE_BUY_STOP   = mt5.ORDER_TYPE_BUY_STOP    # 4
    _ORDER_TYPE_SELL_STOP  = mt5.ORDER_TYPE_SELL_STOP   # 5
    _TRADE_ACTION_DEAL     = 1
    _TRADE_ACTION_PENDING  = mt5.TRADE_ACTION_PENDING   # 5
    _ORDER_FILLING_IOC     = mt5.ORDER_FILLING_IOC
except ImportError:
    _ORDER_TYPE_BUY = 0;  _ORDER_TYPE_SELL = 1
    _ORDER_TYPE_BUY_LIMIT = 2; _ORDER_TYPE_SELL_LIMIT = 3
    _ORDER_TYPE_BUY_STOP = 4; _ORDER_TYPE_SELL_STOP = 5
    _TRADE_ACTION_DEAL = 1; _TRADE_ACTION_PENDING = 5
    _ORDER_FILLING_IOC = 1
```

**3b. Add lookup maps + rename `direction` → `action` in `OrderRequest`:**

```python
_VALID_ORDER_ACTIONS = frozenset({"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"})

_ORDER_TYPE_MAP: dict[str, int] = {
    "BUY":        _ORDER_TYPE_BUY,
    "SELL":       _ORDER_TYPE_SELL,
    "BUY_LIMIT":  _ORDER_TYPE_BUY_LIMIT,
    "SELL_LIMIT": _ORDER_TYPE_SELL_LIMIT,
    "BUY_STOP":   _ORDER_TYPE_BUY_STOP,
    "SELL_STOP":  _ORDER_TYPE_SELL_STOP,
}

_PENDING_ACTIONS = frozenset({"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"})


class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    action: str = Field(..., description="BUY | SELL | BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP")
    volume: float = Field(..., gt=0.0, description="Lot size, must be positive")
    entry_price: float = Field(..., gt=0.0)
    stop_loss: float = Field(..., gt=0.0)
    take_profit: float = Field(..., gt=0.0)
    comment: str = Field(default="AI-Trade", max_length=64)
    deviation: int = Field(default=20, ge=0, description="Max price deviation in points (market orders only)")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v.upper() not in _VALID_ORDER_ACTIONS:
            raise ValueError(f"action must be one of {sorted(_VALID_ORDER_ACTIONS)}")
        return v.upper()
```

**3c. Update `place_order()` — replace the order-building section:**

```python
# Replace the block that builds order_type and mt5_request:
is_pending = request.action in _PENDING_ACTIONS
mt5_action = _TRADE_ACTION_PENDING if is_pending else _TRADE_ACTION_DEAL
order_type  = _ORDER_TYPE_MAP[request.action]
filling_mode = await self._bridge.get_filling_mode(request.symbol)
logger.debug("Filling mode for %s: %s", request.symbol, filling_mode)

mt5_request = {
    "action":       mt5_action,
    "symbol":       request.symbol,
    "volume":       request.volume,
    "type":         order_type,
    "price":        request.entry_price,
    "sl":           request.stop_loss,
    "tp":           request.take_profit,
    "magic":        20250101,
    "comment":      request.comment,
    "type_time":    0,          # ORDER_TIME_GTC
    "type_filling": filling_mode,
}
if not is_pending:
    mt5_request["deviation"] = request.deviation
```

**3d. Update the log line** to use `request.action` instead of `request.direction`:

```python
logger.info(
    "Placing order | symbol=%s action=%s volume=%s entry=%s sl=%s tp=%s",
    request.symbol, request.action, request.volume,
    request.entry_price, request.stop_loss, request.take_profit,
)
```

Also update the kill-switch log lines — replace `request.direction` with `request.action` throughout.

> **Note:** Any callers that build `OrderRequest(direction=...)` must be updated to `action=...`. Check with:
> ```bash
> cd backend && grep -rn "direction=" --include="*.py" | grep -v test | grep -v ".pyc"
> ```

### Step 4: Run tests

```bash
cd backend && uv run pytest tests/test_executor_pending.py -v
```

Expected: all PASS

### Step 5: Run full test suite to catch any `direction=` callsites

```bash
cd backend && uv run pytest -v 2>&1 | tail -30
```

Fix any failing tests that pass `direction=` to `OrderRequest`.

### Step 6: Commit

```bash
git add backend/mt5/executor.py backend/tests/test_executor_pending.py
git commit -m "feat(executor): support pending order types in OrderRequest and place_order"
```

---

## Task 4: Database — model columns + Alembic migration

**Files:**
- Modify: `backend/db/models.py`
- Create: `backend/alembic/versions/<auto>.py`

### Step 1: Add columns to `Trade` model in `backend/db/models.py`

After the `is_paper_trade` column (line ~55), add:

```python
order_type:   Mapped[str] = mapped_column(String(6),  default="market")   # market | limit | stop
order_status: Mapped[str] = mapped_column(String(9),  default="filled")   # pending | filled | cancelled | expired
```

Also expand the `direction` column comment (no schema change, just doc):

```python
direction: Mapped[str] = mapped_column(String(4))  # BUY | SELL (underlying direction)
```

No change to `AIJournal.signal` — `VARCHAR(10)` already fits "BUY_LIMIT" (9 chars).

### Step 2: Generate Alembic migration

```bash
cd backend && uv run alembic revision --autogenerate -m "add_order_type_and_status_to_trades"
```

Open the generated file in `backend/alembic/versions/`. Verify the upgrade contains:

```python
op.add_column("trades", sa.Column("order_type",   sa.String(6),  nullable=False, server_default="market"))
op.add_column("trades", sa.Column("order_status", sa.String(9),  nullable=False, server_default="filled"))
```

And downgrade removes them:

```python
op.drop_column("trades", "order_status")
op.drop_column("trades", "order_type")
```

Fix autogenerate output if needed (Alembic sometimes misses `server_default`).

### Step 3: Apply migration

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 99d8274db526 -> <new_rev>`

### Step 4: Verify with quick DB check

```bash
cd backend && uv run python -c "
import asyncio
from db.postgres import get_db
from sqlalchemy import text

async def check():
    async for db in get_db():
        r = await db.execute(text(\"SELECT order_type, order_status FROM trades LIMIT 1\"))
        print('columns OK:', r.keys())
        break

asyncio.run(check())
"
```

Expected: `columns OK: ['order_type', 'order_status']`

### Step 5: Commit

```bash
git add backend/db/models.py backend/alembic/versions/
git commit -m "feat(db): add order_type and order_status columns to trades"
```

---

## Task 5: Fix `prz_calculator.py` — harmonic uses BUY_LIMIT/SELL_LIMIT

**Files:**
- Modify: `backend/strategies/harmonic/prz_calculator.py`
- Test: `backend/tests/test_harmonic_strategy.py` (update assertions)

### Step 1: Check existing tests that assert on action

```bash
cd backend && grep -n '"BUY"\|"SELL"' tests/test_harmonic_strategy.py tests/test_harmonic_patterns.py tests/test_harmonic_backtest_integration.py
```

Note every assertion that checks `action == "BUY"` or `action == "SELL"` — these need updating.

### Step 2: Update the assertions in harmonic tests

For each test that asserts `result.action == "BUY"` on a harmonic signal, change to `"BUY_LIMIT"`.
For `"SELL"` assertions from harmonic patterns, change to `"SELL_LIMIT"`.

Example pattern:
```python
# Before
assert result.action == "BUY"

# After
assert result.action == "BUY_LIMIT"
```

### Step 3: Run tests to verify they now fail (expected — prz_calculator not changed yet)

```bash
cd backend && uv run pytest tests/test_harmonic_strategy.py tests/test_harmonic_patterns.py tests/test_harmonic_backtest_integration.py -v 2>&1 | grep -E "PASSED|FAILED"
```

### Step 4: Implement in `backend/strategies/harmonic/prz_calculator.py`

Replace line ~68:

```python
# Before
action = "BUY" if is_bullish else "SELL"

# After — PRZ entries are pending; price must reach D point
action = "BUY_LIMIT" if is_bullish else "SELL_LIMIT"
```

### Step 5: Run tests to verify they pass

```bash
cd backend && uv run pytest tests/test_harmonic_strategy.py tests/test_harmonic_patterns.py tests/test_harmonic_backtest_integration.py -v
```

Expected: all PASS

### Step 6: Commit

```bash
git add backend/strategies/harmonic/prz_calculator.py backend/tests/test_harmonic_strategy.py backend/tests/test_harmonic_patterns.py backend/tests/test_harmonic_backtest_integration.py
git commit -m "feat(harmonic): emit BUY_LIMIT/SELL_LIMIT for PRZ entries"
```

---

## Task 6: Frontend TypeScript types

**Files:**
- Modify: `frontend/src/types/trading.ts`

### Step 1: Review current type file

Open `frontend/src/types/trading.ts` and locate all places where action/signal union types are defined (lines 95, 114, 187, 281, 362, 420).

### Step 2: Add shared `OrderAction` type and update all usages

At the top of the types section (after imports), add:

```typescript
// All possible trading actions — market and pending orders
export type OrderAction =
  | "BUY"
  | "SELL"
  | "BUY_LIMIT"
  | "SELL_LIMIT"
  | "BUY_STOP"
  | "SELL_STOP"
  | "HOLD";
```

Then update each interface:

```typescript
// Trade (line ~95) — direction stays BUY/SELL; add order_type + order_status
export interface Trade {
  // ...existing fields...
  direction: "BUY" | "SELL";                                                          // unchanged
  order_type?: "market" | "limit" | "stop";                                           // NEW
  order_status?: "pending" | "filled" | "cancelled" | "expired";                      // NEW
}

// AISignal (line ~114)
signal: OrderAction;                    // was: "BUY" | "SELL" | "HOLD"

// AnalyzeResult (line ~187)
action: OrderAction;                    // was: "BUY" | "SELL" | "HOLD"

// StrategyRun (line ~281)
action: OrderAction;                    // was: "BUY" | "SELL" | "HOLD"

// PipelineRunSummary (line ~362)
final_action: OrderAction | null;       // was: "BUY" | "SELL" | "HOLD" | null
```

`BacktestTrade.direction` stays `"BUY" | "SELL"` — backtest only records fills.

### Step 3: Check for TypeScript errors

```bash
cd frontend && npm run build 2>&1 | grep -E "error TS|Type error"
```

Expected: no errors. If any component switches on the signal type with an exhaustive check, add the new cases.

### Step 4: Commit

```bash
git add frontend/src/types/trading.ts
git commit -m "feat(frontend): add pending order action types to TypeScript interfaces"
```

---

## Task 7: Full regression — run all backend tests

### Step 1: Run full test suite

```bash
cd backend && uv run pytest -v 2>&1 | tail -40
```

Expected: all tests PASS. If any fail:
- Tests that mock `OrderRequest(direction=...)` → update to `action=`
- Tests that assert `action == "BUY"` on harmonic signals → update to `action == "BUY_LIMIT"`

### Step 2: Final commit if any test fixes were needed

```bash
git add -p   # stage only test file changes
git commit -m "test: update test fixtures for pending order action types"
```

---

## Implementation Order Summary

```
Task 1: base_strategy.py    — StrategyResult + helpers + MultiAgentStrategy fix
Task 2: orchestrator.py     — TradingSignal + prompt + normalizer
Task 3: executor.py         — OrderRequest.action + place_order branching
Task 4: models.py + alembic — DB columns + migration
Task 5: prz_calculator.py   — harmonic BUY_LIMIT/SELL_LIMIT
Task 6: trading.ts          — TypeScript types
Task 7: full regression     — catch any remaining callsites
```

Tasks 1–3 are fully independent and can be done in any order. Task 4 requires Task 3 (executor uses `action` field). Task 5 depends on Task 1. Task 6 is independent.
