# Position Maintenance Task Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a scheduled AI-driven position maintenance task that reviews all open positions and pending orders, runs a 3-role LLM pipeline (technical → sentiment → decision), validates constraints, and executes hold/close/modify actions with full pipeline tracing.

**Architecture:** New `PositionMaintenanceService` in `services/position_maintenance.py`, a `review_position()` function added to `ai/orchestrator.py`, and `modify_order()` added to `mt5/executor.py`. APScheduler fires a single global job every `maintenance_interval_minutes` (from Settings). Enable/disable switches live on `strategies.maintenance_enabled` and `trades.maintenance_enabled`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, APScheduler, LangChain (existing), Alembic, Next.js 16, TypeScript, Tailwind, shadcn/ui

---

## Task 1: DB Migration — Add maintenance columns

**Files:**
- Create: `backend/alembic/versions/<hash>_add_position_maintenance.py`
- Modify: `backend/db/models.py`

**Step 1: Generate a blank Alembic revision**

Run from `backend/`:
```bash
uv run alembic revision --autogenerate -m "add_position_maintenance"
```

This creates `backend/alembic/versions/<hash>_add_position_maintenance.py`. Open the generated file and replace its `upgrade()` and `downgrade()` functions with the ones below.

**Step 2: Write the migration**

In the generated file, write:
```python
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '<hash>'           # auto-filled by alembic
down_revision = '9776cc107398'     # update to actual latest revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('strategies', sa.Column(
        'maintenance_enabled', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('trades', sa.Column(
        'maintenance_enabled', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('pipeline_runs', sa.Column(
        'task_type', sa.String(length=20), nullable=False, server_default='signal'))


def downgrade() -> None:
    op.drop_column('pipeline_runs', 'task_type')
    op.drop_column('trades', 'maintenance_enabled')
    op.drop_column('strategies', 'maintenance_enabled')
```

**Step 3: Update models.py**

In `backend/db/models.py`, add `maintenance_enabled` to Strategy (after `is_active`):
```python
    maintenance_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
```

Add `maintenance_enabled` to Trade (after `is_paper_trade`):
```python
    maintenance_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
```

Add `task_type` to PipelineRun (after `timeframe`):
```python
    task_type: Mapped[str] = mapped_column(String(20), default="signal")
    # "signal" | "maintenance"
```

Also update `_strategy_init_defaults` listener to include:
```python
    kwargs.setdefault("maintenance_enabled", True)
```

**Step 4: Apply the migration**

Run from `backend/`:
```bash
uv run alembic upgrade head
```

Expected output ends with: `Running upgrade ... -> <hash>, add_position_maintenance`

**Step 5: Verify**

```bash
uv run alembic current
```

Expected: shows `<hash> (head)`

---

## Task 2: Config — maintenance_interval_minutes

**Files:**
- Modify: `backend/core/config.py`

**Step 1: Add the setting**

In `backend/core/config.py`, add after `default_risk_percent`:
```python
    # ── Maintenance Task ───────────────────────────────────────────────────────
    maintenance_interval_minutes: int = 60  # set MAINTENANCE_INTERVAL_MINUTES in .env
    maintenance_task_enabled: bool = True   # set MAINTENANCE_TASK_ENABLED=false to disable globally
```

Add a validator after `validate_default_risk`:
```python
    @field_validator("maintenance_interval_minutes")
    @classmethod
    def validate_maintenance_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"maintenance_interval_minutes must be >= 1, got {v}")
        return v
```

**Step 2: Verify no startup errors**

Run from `backend/` (stops after startup check — Ctrl+C is fine):
```bash
uv run uvicorn main:app --reload --port 8000
```

Expected: No `ValueError` in startup output.

---

## Task 3: MT5 Bridge — get_orders() and modify_position()

**Files:**
- Modify: `backend/mt5/bridge.py`

**Step 1: Add get_orders() after get_positions()**

In `backend/mt5/bridge.py`, after the `get_positions()` method, add:
```python
    async def get_orders(self, symbol: str | None = None) -> list[dict]:
        """Fetch pending (unfilled) orders. Returns empty list if none."""
        self._require_mt5()
        if symbol:
            raw = await self._run(mt5.orders_get, symbol=symbol)
        else:
            raw = await self._run(mt5.orders_get)
        return [o._asdict() for o in raw] if raw else []

    async def modify_position_sltp(
        self,
        ticket: int,
        symbol: str,
        new_sl: float,
        new_tp: float,
    ) -> dict | None:
        """Modify the SL/TP of an existing open position.

        Uses TRADE_ACTION_SLTP which does NOT require a price or deviation.
        Returns the order_send result dict, or None on MT5 API failure.
        """
        self._require_mt5()
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": new_sl,
            "tp": new_tp,
            "magic": 20250101,
        }
        result = await self._run(partial(mt5.order_send, **request))
        return result._asdict() if result else None
```

The `TRADE_ACTION_SLTP` constant is already imported via the try/except block at the top. Verify `mt5.TRADE_ACTION_SLTP` is available (it's value `6`). If the constants block doesn't include it, add `_TRADE_ACTION_SLTP = mt5.TRADE_ACTION_SLTP` (value `6`) to both try and except branches in executor.py Task 4 below.

---

## Task 4: MT5 Executor — modify_order()

**Files:**
- Modify: `backend/mt5/executor.py`

**Step 1: Add TRADE_ACTION_SLTP constant**

In the try/except import block at the top of `backend/mt5/executor.py`, add to both branches:

In `try:`:
```python
    _TRADE_ACTION_SLTP = mt5.TRADE_ACTION_SLTP   # 6
```
In `except ImportError:`:
```python
    _TRADE_ACTION_SLTP = 6
```

**Step 2: Add modify_order() to MT5Executor**

After `close_position()`, add:
```python
    async def modify_order(
        self,
        ticket: int,
        symbol: str,
        new_sl: float,
        new_tp: float,
        dry_run: bool = False,
    ) -> OrderResult:
        """Modify the stop loss and take profit of an existing open position.

        Uses TRADE_ACTION_SLTP — no price deviation needed.
        Kill switch is checked before the MT5 call.
        """
        if kill_switch_active():
            logger.warning(
                "Modify rejected — kill switch active | ticket=%s symbol=%s",
                ticket, symbol,
            )
            return OrderResult(success=False, error="Kill switch is active")

        if dry_run:
            logger.info(
                "DRY RUN modify | ticket=%s symbol=%s new_sl=%s new_tp=%s",
                ticket, symbol, new_sl, new_tp,
            )
            return OrderResult(success=True, ticket=ticket, retcode=10009)

        logger.info(
            "Modifying position | ticket=%s symbol=%s new_sl=%s new_tp=%s",
            ticket, symbol, new_sl, new_tp,
        )

        result = await self._bridge.modify_position_sltp(ticket, symbol, new_sl, new_tp)
        if not result:
            code, msg = await self._bridge.get_last_error()
            logger.error(
                "Modify send failed | ticket=%s | code=%s msg=%s", ticket, code, msg
            )
            return OrderResult(success=False, error=msg, retcode=code)

        retcode = result.get("retcode", -1)
        if retcode == 10009:
            logger.info("Position modified | ticket=%s symbol=%s", ticket, symbol)
            return OrderResult(success=True, ticket=ticket, retcode=retcode)

        error_msg = result.get("comment", "Unknown error")
        logger.error(
            "Modify rejected by broker | ticket=%s retcode=%s error=%s",
            ticket, retcode, error_msg,
        )
        return OrderResult(success=False, error=error_msg, retcode=retcode)
```

---

## Task 5: PipelineTracer — task_type support

**Files:**
- Modify: `backend/services/pipeline_tracer.py`

**Step 1: Update __init__ and __aenter__**

Update `PipelineTracer.__init__` to accept `task_type`:
```python
    def __init__(
        self,
        account_id: int,
        symbol: str,
        timeframe: str,
        task_type: str = "signal",
    ) -> None:
        self._account_id = account_id
        self._symbol = symbol
        self._timeframe = timeframe
        self._task_type = task_type
        # ... rest unchanged
```

Update `__aenter__` when creating `PipelineRun`:
```python
        self._run = PipelineRun(
            account_id=self._account_id,
            symbol=self._symbol,
            timeframe=self._timeframe,
            task_type=self._task_type,
            status="running",
        )
```

This change is backward-compatible — all existing callers keep `task_type="signal"` by default.

---

## Task 6: Orchestrator — review_position() 3-role pipeline

**Files:**
- Modify: `backend/ai/orchestrator.py`

**Step 1: Add MaintenanceDecision schema and MaintenanceResult dataclass**

After `LLMAnalysisResult` dataclass definition, add:

```python
_VALID_MAINTENANCE_ACTIONS = frozenset({"HOLD", "CLOSE", "MODIFY"})


class MaintenanceDecision(BaseModel):
    """LLM output from the maintenance_decision role."""
    action: str = Field(..., description="HOLD | CLOSE | MODIFY")
    new_sl: float | None = Field(None, description="New stop loss price (MODIFY only)")
    new_tp: float | None = Field(None, description="New take profit price (MODIFY only)")
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., description="1-2 sentence explanation")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v.upper() not in _VALID_MAINTENANCE_ACTIONS:
            raise ValueError(f"action must be one of {sorted(_VALID_MAINTENANCE_ACTIONS)}")
        return v.upper()


@dataclass
class MaintenanceResult:
    """Combined result from the 3-role maintenance pipeline."""
    decision: MaintenanceDecision
    technical_analysis: LLMRoleResult
    sentiment_analysis: LLMRoleResult
    maintenance_decision: LLMRoleResult
```

**Step 2: Add maintenance system prompts**

After `_EXECUTION_SYSTEM`, add:

```python
_MAINTENANCE_TECHNICAL_SYSTEM = """You are a professional forex technical analyst reviewing an existing open position.
Analyze the position's technical merit given current market conditions.
Return ONLY strictly valid JSON:
{
  "trend": "uptrend | downtrend | ranging",
  "trend_strength": <float 0.0-1.0>,
  "key_support": <float>,
  "key_resistance": <float>,
  "position_alignment": "aligned | misaligned | neutral",
  "technical_score": <float -1.0 to 1.0>,
  "notes": "<2-3 sentences on technical outlook for this position>"
}"""

_MAINTENANCE_SENTIMENT_SYSTEM = """You are a professional forex market analyst assessing news sentiment impact.
Given upcoming economic events and recent news, assess directional sentiment for the symbol.
Return ONLY strictly valid JSON:
{
  "sentiment_direction": "BULLISH | BEARISH | NEUTRAL",
  "event_risk": "HIGH | MEDIUM | LOW",
  "key_events": ["<event 1>", "<event 2>"],
  "sentiment_score": <float -1.0 to 1.0>,
  "notes": "<2 sentences on news impact for this symbol>"
}"""

_MAINTENANCE_DECISION_SYSTEM = """You are a professional forex risk manager reviewing an open position.
Given the technical analysis, sentiment analysis, and the position's current state,
recommend whether to HOLD, CLOSE, or MODIFY the position's SL/TP.

You MUST adhere to the strategy constraints provided. When suggesting MODIFY:
- new_sl and new_tp must respect the minimum SL distance (sl_pips)
- For profitable positions: new_sl must move toward profit (trailing logic)
- new_tp must maintain at least 1:1 R:R relative to new_sl distance from entry

Return ONLY strictly valid JSON:
{
  "action": "HOLD | CLOSE | MODIFY",
  "new_sl": <float or null>,
  "new_tp": <float or null>,
  "confidence": <float 0.0-1.0>,
  "rationale": "<1-2 sentence explanation>"
}

Rules:
- Signal CLOSE if position is strongly misaligned with current technical + sentiment.
- Signal MODIFY only when SL/TP improvements are clearly justified.
- Signal HOLD when uncertain or when the position is performing as expected.
- NEVER suggest modifications that increase risk beyond the strategy's risk_pct."""
```

**Step 3: Add the 3 private role functions**

After `_run_execution_decision`, add:

```python
# ── Maintenance Roles ──────────────────────────────────────────────────────────

async def _run_maintenance_technical(
    llm: BaseChatModel,
    symbol: str,
    timeframe: str,
    ohlcv: list[dict],
    indicators: dict,
    position: dict,
    strategy_params: dict,
) -> LLMRoleResult:
    """Role 1: Technical analysis of the existing position."""
    human = "\n".join([
        f"Symbol: {symbol} | Timeframe: {timeframe}",
        f"\nPosition State:\n{json.dumps(position, indent=2, default=str)}",
        f"\nIndicators:\n{json.dumps(indicators, indent=2)}",
        f"\nStrategy Params:\n{json.dumps(strategy_params, indent=2)}",
        f"\nLast 20 OHLCV candles (oldest → newest):\n{json.dumps(ohlcv[-20:], indent=2, default=str)}",
        "\nProvide the technical analysis JSON.",
    ])
    messages = [
        SystemMessage(content=_MAINTENANCE_TECHNICAL_SYSTEM),
        HumanMessage(content=human),
    ]
    return await _call_llm_for_role(llm, messages, "maintenance_technical")


async def _run_maintenance_sentiment(
    llm: BaseChatModel,
    symbol: str,
    news_context: str | None,
    trade_history_context: str | None,
) -> LLMRoleResult:
    """Role 2: News sentiment analysis for the symbol."""
    human_parts = [f"Symbol: {symbol}"]
    if news_context:
        human_parts.append(f"\nUpcoming News & Events:\n{news_context}")
    else:
        human_parts.append("\nNo news data available — assess NEUTRAL sentiment.")
    if trade_history_context:
        human_parts.append(f"\nRecent Trade History:\n{trade_history_context}")
    human_parts.append("\nProvide the sentiment analysis JSON.")
    messages = [
        SystemMessage(content=_MAINTENANCE_SENTIMENT_SYSTEM),
        HumanMessage(content="\n".join(human_parts)),
    ]
    return await _call_llm_for_role(llm, messages, "maintenance_sentiment")


async def _run_maintenance_decision(
    llm: BaseChatModel,
    symbol: str,
    position: dict,
    technical_output: dict,
    sentiment_output: dict,
    strategy_params: dict,
) -> LLMRoleResult:
    """Role 3: Final hold/close/modify decision."""
    human = "\n".join([
        f"Symbol: {symbol}",
        f"\nPosition State:\n{json.dumps(position, indent=2, default=str)}",
        f"\nStrategy Constraints:\n{json.dumps(strategy_params, indent=2)}",
        f"\nTechnical Analysis:\n{json.dumps(technical_output, indent=2, default=str)}",
        f"\nSentiment Analysis:\n{json.dumps(sentiment_output, indent=2, default=str)}",
        "\nProvide the maintenance decision JSON.",
    ])
    messages = [
        SystemMessage(content=_MAINTENANCE_DECISION_SYSTEM),
        HumanMessage(content=human),
    ]
    return await _call_llm_for_role(llm, messages, "maintenance_decision")
```

**Step 4: Add the public review_position() function**

At the bottom of `backend/ai/orchestrator.py`, add:

```python
# ── Public: Maintenance Pipeline ───────────────────────────────────────────────

async def review_position(
    symbol: str,
    timeframe: str,
    ohlcv: list[dict],
    indicators: dict,
    position: dict,
    strategy_params: dict,
    news_context: str | None = None,
    trade_history_context: str | None = None,
    *,
    technical_llm: BaseChatModel | None = None,
    sentiment_llm: BaseChatModel | None = None,
    decision_llm: BaseChatModel | None = None,
) -> MaintenanceResult:
    """3-role LLM maintenance pipeline: technical → sentiment → decision.

    Args:
        symbol: Instrument symbol (e.g. 'EURUSD').
        timeframe: Strategy timeframe (e.g. 'H1').
        ohlcv: List of OHLCV candle dicts (last 20 sufficient).
        indicators: Dict of computed indicator values.
        position: Dict with position state (ticket, direction, entry_price,
                  current_price, current_sl, current_tp, unrealized_pnl,
                  volume, duration_hours).
        strategy_params: Dict with sl_pips, tp_pips, risk_pct, max_lot_size.
        news_context: Optional formatted news string from MarketContext.
        trade_history_context: Optional formatted trade history string.
        technical_llm: Override LLM for role 1. Uses default provider if None.
        sentiment_llm: Override LLM for role 2. Uses default provider if None.
        decision_llm: Override LLM for role 3. Uses default provider if None.

    Returns:
        MaintenanceResult with parsed decision and all 3 role results.
    """
    llm_technical = technical_llm or _build_llm()
    llm_sentiment = sentiment_llm or _build_llm()
    llm_decision = decision_llm or _build_llm()

    # Role 1: Technical analysis
    tech_result = await _run_maintenance_technical(
        llm_technical, symbol, timeframe, ohlcv, indicators, position, strategy_params
    )

    # Role 2: Sentiment analysis
    sent_result = await _run_maintenance_sentiment(
        llm_sentiment, symbol, news_context, trade_history_context
    )

    # Role 3: Final decision (receives outputs of roles 1 and 2)
    tech_output = tech_result.content if isinstance(tech_result.content, dict) else {}
    sent_output = sent_result.content if isinstance(sent_result.content, dict) else {}
    dec_result = await _run_maintenance_decision(
        llm_decision, symbol, position, tech_output, sent_output, strategy_params
    )

    # Parse MaintenanceDecision from role 3 output
    raw = dec_result.content if isinstance(dec_result.content, dict) else {}
    raw.setdefault("action", "HOLD")
    raw.setdefault("confidence", 0.0)
    raw.setdefault("rationale", "No rationale provided.")
    if isinstance(raw.get("action"), str):
        raw["action"] = raw["action"].upper()

    try:
        decision = MaintenanceDecision(**raw)
    except Exception as exc:
        logger.warning("MaintenanceDecision parse failed (%s) — defaulting to HOLD: %s", exc, raw)
        decision = MaintenanceDecision(
            action="HOLD", confidence=0.0, rationale=f"Parse error: {exc}"
        )

    # Confidence gate: downgrade to HOLD if below threshold
    if decision.action != "HOLD" and decision.confidence < settings.llm_confidence_threshold:
        logger.info(
            "Maintenance decision downgraded HOLD (confidence %.2f < threshold %.2f)",
            decision.confidence, settings.llm_confidence_threshold,
        )
        decision = MaintenanceDecision(
            action="HOLD",
            confidence=decision.confidence,
            rationale=f"Confidence {decision.confidence:.2f} below threshold — HOLD",
        )

    return MaintenanceResult(
        decision=decision,
        technical_analysis=tech_result,
        sentiment_analysis=sent_result,
        maintenance_decision=dec_result,
    )
```

---

## Task 7: PositionMaintenanceService

**Files:**
- Create: `backend/services/position_maintenance.py`

**Step 1: Write the service**

```python
"""Position Maintenance Service — scheduled AI review of open positions and pending orders.

For each eligible position:
  1. Fetch OHLCV (Redis cache by TF)
  2. LLM Role 1: maintenance_technical_analysis
  3. LLM Role 2: maintenance_sentiment_analysis
  4. LLM Role 3: maintenance_decision → HOLD | CLOSE | MODIFY
  5. ConstraintValidator — validate MODIFY against strategy rules
  6. MT5 action (skip / close_position / modify_order)

Every position run is traced via PipelineTracer (task_type="maintenance").
"""
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.orchestrator import review_position
from core.config import settings
from core.llm_pricing import compute_cost
from core.security import decrypt
from db.models import Account, AccountStrategy, Strategy, Trade
from db.redis import get_candle_cache, set_candle_cache
from mt5.bridge import AccountCredentials, MT5Bridge
from mt5.executor import MT5Executor
from services.kill_switch import is_active as kill_switch_active
from services.market_context import MarketContext
from services.history_sync import HistoryService
from services.pipeline_tracer import PipelineTracer

logger = logging.getLogger(__name__)

# MT5 timeframe integer map (same as ai_trading.py)
_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769,
}

_CACHE_TTL: dict[str, int] = {
    "M1": 30, "M5": 30, "M15": 60, "M30": 120,
    "H1": 300, "H4": 600, "D1": 1800, "W1": 3600,
}

_PIP_SIZE: dict[str, float] = {
    "XAUUSD": 0.1, "XAGUSD": 0.001,
}
_DEFAULT_PIP_SIZE = 0.0001  # standard forex pairs


def _get_pip_size(symbol: str) -> float:
    return _PIP_SIZE.get(symbol.upper(), _DEFAULT_PIP_SIZE)


# ── Constraint Validator ───────────────────────────────────────────────────────

@dataclass
class ConstraintResult:
    passed: bool
    reason: str | None = None


def validate_modify(
    *,
    direction: str,            # "BUY" or "SELL"
    entry_price: float,
    current_price: float,
    current_sl: float,
    volume: float,
    balance: float,
    new_sl: float,
    new_tp: float,
    sl_pips: float,
    risk_pct: float,
    symbol: str,
) -> ConstraintResult:
    """Validate an LLM-suggested MODIFY against strategy risk constraints.

    Returns ConstraintResult(passed=True) if all checks pass, or
    ConstraintResult(passed=False, reason=...) with the first violated rule.
    """
    pip_size = _get_pip_size(symbol)

    # 1. Minimum SL distance from current price
    sl_distance = abs(current_price - new_sl)
    min_sl_distance = sl_pips * pip_size
    if sl_distance < min_sl_distance:
        return ConstraintResult(
            passed=False,
            reason=(
                f"new_sl too close: distance={sl_distance:.5f} < "
                f"min={min_sl_distance:.5f} ({sl_pips} pips)"
            ),
        )

    # 2. Trailing stop logic — SL may only move in favorable direction
    entry_to_current = current_price - entry_price if direction == "BUY" else entry_price - current_price
    if entry_to_current > 0:  # position is in profit
        if direction == "BUY" and new_sl < current_sl:
            return ConstraintResult(
                passed=False,
                reason=(
                    f"trailing stop violated: BUY position in profit, "
                    f"new_sl {new_sl} < current_sl {current_sl}"
                ),
            )
        if direction == "SELL" and new_sl > current_sl:
            return ConstraintResult(
                passed=False,
                reason=(
                    f"trailing stop violated: SELL position in profit, "
                    f"new_sl {new_sl} > current_sl {current_sl}"
                ),
            )

    # 3. Max risk per trade: new SL must not risk more than risk_pct of balance
    new_sl_distance_pips = abs(current_price - new_sl) / pip_size
    # Approximate pip value per lot for major pairs (simplified)
    approx_pip_value = 10.0  # USD per pip per standard lot (approximate)
    max_risk_usd = balance * risk_pct
    actual_risk_usd = new_sl_distance_pips * approx_pip_value * volume
    if actual_risk_usd > max_risk_usd * 1.2:  # 20% tolerance
        return ConstraintResult(
            passed=False,
            reason=(
                f"max risk exceeded: risk={actual_risk_usd:.2f} USD > "
                f"max={max_risk_usd:.2f} USD ({risk_pct*100:.1f}% of {balance:.2f})"
            ),
        )

    # 4. Minimum R:R — new_tp must be at least 1:1 from entry vs new_sl
    if direction == "BUY":
        sl_dist = abs(entry_price - new_sl)
        tp_dist = abs(new_tp - entry_price)
    else:
        sl_dist = abs(entry_price - new_sl)
        tp_dist = abs(entry_price - new_tp)

    if sl_dist > 0 and tp_dist < sl_dist:
        return ConstraintResult(
            passed=False,
            reason=(
                f"R:R below 1:1: TP distance {tp_dist:.5f} < SL distance {sl_dist:.5f}"
            ),
        )

    return ConstraintResult(passed=True)


# ── PositionMaintenanceService ─────────────────────────────────────────────────

class PositionMaintenanceService:

    async def run_maintenance_sweep(self, db: AsyncSession) -> None:
        """Entry point called by APScheduler. Sweeps all active accounts."""
        logger.info(
            "Maintenance sweep started | interval=%dmin",
            settings.maintenance_interval_minutes,
        )

        if not settings.maintenance_task_enabled:
            logger.info("Maintenance task globally disabled — skipping sweep")
            return

        # Fetch all active accounts with at least one active maintenance-enabled strategy
        result = await db.execute(
            select(Account)
            .where(Account.is_active.is_(True))
        )
        accounts = result.scalars().all()

        totals = {"hold": 0, "close": 0, "modify": 0, "skip": 0, "error": 0}

        for account in accounts:
            try:
                counts = await self._process_account(account, db)
                for k, v in counts.items():
                    totals[k] += v
            except Exception:
                logger.exception("Maintenance sweep failed for account=%d", account.id)
                totals["error"] += 1

        logger.info(
            "Maintenance sweep complete | HOLD=%d CLOSE=%d MODIFY=%d SKIP=%d ERR=%d",
            totals["hold"], totals["close"], totals["modify"],
            totals["skip"], totals["error"],
        )

    async def _process_account(
        self, account: Account, db: AsyncSession
    ) -> dict[str, int]:
        """Process all eligible positions/orders for a single account."""
        counts = {"hold": 0, "close": 0, "modify": 0, "skip": 0, "error": 0}

        # Kill switch check
        if kill_switch_active():
            logger.warning(
                "Maintenance account=%d skipped — kill switch active", account.id
            )
            counts["skip"] += 999
            return counts

        # Fetch active maintenance-enabled strategies bound to this account
        strat_result = await db.execute(
            select(AccountStrategy)
            .where(
                AccountStrategy.account_id == account.id,
                AccountStrategy.is_active.is_(True),
            )
        )
        bindings = strat_result.scalars().all()

        # Build set of strategy IDs that have maintenance_enabled=True
        strategy_ids: set[int] = set()
        strategies_by_id: dict[int, Strategy] = {}
        for binding in bindings:
            strat = await db.get(Strategy, binding.strategy_id)
            if strat and strat.is_active and strat.maintenance_enabled:
                strategy_ids.add(strat.id)
                strategies_by_id[strat.id] = strat

        if not strategy_ids:
            logger.debug("Account=%d: no maintenance-enabled strategies", account.id)
            return counts

        # Fetch open positions and pending orders from DB (only for this account's strategies)
        # We use Trade rows to identify which positions have maintenance_enabled
        trade_result = await db.execute(
            select(Trade).where(
                Trade.account_id == account.id,
                Trade.order_status.in_(["filled", "pending"]),
                Trade.closed_at.is_(None),
                Trade.strategy_id.in_(strategy_ids),
                Trade.maintenance_enabled.is_(True),
            )
        )
        eligible_trades = trade_result.scalars().all()

        if not eligible_trades:
            logger.info("Account=%d: 0 eligible positions for maintenance", account.id)
            return counts

        logger.info(
            "Account=%d (%s): %d positions eligible for maintenance",
            account.id, account.name, len(eligible_trades),
        )

        # Connect to MT5 once for this account
        password = decrypt(account.password_encrypted)
        creds = AccountCredentials(
            login=account.login,
            password=password,
            server=account.server,
            path=account.mt5_path or settings.mt5_path,
        )

        try:
            async with MT5Bridge(creds) as bridge:
                # Fetch all live positions and pending orders from MT5 once
                mt5_positions = await bridge.get_positions()
                mt5_orders = await bridge.get_orders()
                mt5_by_ticket: dict[int, dict] = {
                    p["ticket"]: p for p in mt5_positions + mt5_orders
                }

                account_info = await bridge.get_account_info()
                balance = account_info["balance"] if account_info else 10000.0

                for trade in eligible_trades:
                    mt5_pos = mt5_by_ticket.get(trade.ticket)
                    strategy = strategies_by_id.get(trade.strategy_id)

                    if not mt5_pos or not strategy:
                        counts["skip"] += 1
                        continue

                    try:
                        action = await self._run_single_maintenance(
                            trade=trade,
                            mt5_pos=mt5_pos,
                            strategy=strategy,
                            bridge=bridge,
                            balance=balance,
                            account=account,
                            db=db,
                        )
                        counts[action.lower()] = counts.get(action.lower(), 0) + 1
                    except Exception:
                        logger.exception(
                            "Maintenance failed | account=%d ticket=%d",
                            account.id, trade.ticket,
                        )
                        counts["error"] += 1

        except ConnectionError as exc:
            logger.warning(
                "Maintenance account=%d MT5 unavailable: %s", account.id, exc
            )
            counts["error"] += len(eligible_trades)

        return counts

    async def _run_single_maintenance(
        self,
        *,
        trade: Trade,
        mt5_pos: dict,
        strategy: Strategy,
        bridge: MT5Bridge,
        balance: float,
        account: Account,
        db: AsyncSession,
    ) -> str:
        """Run maintenance pipeline for one position. Returns the final action taken."""
        symbol = trade.symbol
        timeframe = strategy.timeframe or "H1"

        async with PipelineTracer(
            account.id, symbol, timeframe, task_type="maintenance"
        ) as tracer:
            # ── Step 1: Fetch OHLCV ────────────────────────────────────────────
            t0 = time.monotonic()
            tf_int = _TIMEFRAME_MAP.get(timeframe, 16385)  # default H1
            cache_key = f"ohlcv:{symbol}:{timeframe}"
            cache_ttl = _CACHE_TTL.get(timeframe, 300)

            ohlcv = await get_candle_cache(cache_key)
            if not ohlcv:
                ohlcv = await bridge.get_rates(symbol, tf_int, 50)
                if ohlcv:
                    await set_candle_cache(cache_key, ohlcv, cache_ttl)

            await tracer.record(
                "ohlcv_fetch",
                output_data={"count": len(ohlcv), "cached": False},
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

            if not ohlcv:
                tracer.finalize(status="skipped", final_action="HOLD")
                return "HOLD"

            # ── Step 2: Compute indicators ────────────────────────────────────
            closes = [c["close"] for c in ohlcv[-20:]]
            sma20 = sum(closes) / len(closes) if closes else 0.0
            indicators = {
                "sma20": round(sma20, 5),
                "high_20": round(max(c["high"] for c in ohlcv[-20:]), 5),
                "low_20": round(min(c["low"] for c in ohlcv[-20:]), 5),
            }
            tick = await bridge.get_tick(symbol)
            current_price = tick["bid"] if tick else (closes[-1] if closes else 0.0)

            # ── Build position context dict ───────────────────────────────────
            opened_at = trade.opened_at
            duration_hours = (
                (datetime.now(UTC) - opened_at).total_seconds() / 3600
                if opened_at else 0.0
            )
            position_ctx = {
                "ticket": trade.ticket,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "current_price": current_price,
                "current_sl": mt5_pos.get("sl", trade.stop_loss),
                "current_tp": mt5_pos.get("tp", trade.take_profit),
                "unrealized_pnl": mt5_pos.get("profit", 0.0),
                "volume": trade.volume,
                "duration_hours": round(duration_hours, 1),
                "order_type": trade.order_type,
                "order_status": trade.order_status,
            }
            strategy_params = {
                "sl_pips": strategy.sl_pips or 20.0,
                "tp_pips": strategy.tp_pips or 40.0,
                "risk_pct": account.risk_pct,
                "max_lot_size": account.max_lot_size,
            }

            await tracer.record(
                "context_built",
                output_data={"position": position_ctx, "indicators": indicators},
                duration_ms=0,
            )

            # ── Step 3-5: LLM 3-role pipeline ─────────────────────────────────
            # Fetch news context (optional)
            news_ctx = None
            if settings.news_enabled:
                try:
                    mc = MarketContext()
                    news_ctx = await mc.get_upcoming_events_text(symbol)
                except Exception as exc:
                    logger.debug("News context fetch failed (non-critical): %s", exc)

            # Fetch trade history context
            history_ctx = None
            try:
                hs = HistoryService(bridge, db)
                history_ctx = await hs.get_history_context(account.id, symbol, days=14)
            except Exception as exc:
                logger.debug("History context fetch failed (non-critical): %s", exc)

            t0 = time.monotonic()
            result = await review_position(
                symbol=symbol,
                timeframe=timeframe,
                ohlcv=ohlcv,
                indicators=indicators,
                position=position_ctx,
                strategy_params=strategy_params,
                news_context=news_ctx,
                trade_history_context=history_ctx,
            )
            llm_duration = int((time.monotonic() - t0) * 1000)

            # Record each LLM role
            for role_result, role_name in [
                (result.technical_analysis, "maintenance_technical"),
                (result.sentiment_analysis, "maintenance_sentiment"),
                (result.maintenance_decision, "maintenance_decision"),
            ]:
                step_id = await tracer.record(
                    role_name,
                    output_data={"content": role_result.content},
                    duration_ms=role_result.duration_ms,
                )
                cost = compute_cost(
                    role_result.provider,
                    role_result.model,
                    role_result.input_tokens or 0,
                    role_result.output_tokens or 0,
                )
                await tracer.record_llm_call(
                    role=role_name,
                    provider=role_result.provider,
                    model=role_result.model,
                    input_tokens=role_result.input_tokens,
                    output_tokens=role_result.output_tokens,
                    total_tokens=role_result.total_tokens,
                    cost_usd=cost,
                    duration_ms=role_result.duration_ms,
                    pipeline_step_id=step_id,
                )

            decision = result.decision

            # ── Step 6: Constraint validation ─────────────────────────────────
            final_action = decision.action
            constraint_reason: str | None = None

            if decision.action == "MODIFY" and decision.new_sl is not None and decision.new_tp is not None:
                current_sl = mt5_pos.get("sl", trade.stop_loss)
                cv = validate_modify(
                    direction=trade.direction,
                    entry_price=trade.entry_price,
                    current_price=current_price,
                    current_sl=current_sl,
                    volume=trade.volume,
                    balance=balance,
                    new_sl=decision.new_sl,
                    new_tp=decision.new_tp,
                    sl_pips=strategy.sl_pips or 20.0,
                    risk_pct=account.risk_pct,
                    symbol=symbol,
                )
                if not cv.passed:
                    logger.info(
                        "MODIFY downgraded to HOLD (constraint: %s) | ticket=%d",
                        cv.reason, trade.ticket,
                    )
                    final_action = "HOLD"
                    constraint_reason = cv.reason
                    await tracer.record(
                        "constraint_rejected",
                        status="ok",
                        output_data={
                            "original_action": "MODIFY",
                            "downgraded_to": "HOLD",
                            "reason": cv.reason,
                            "llm_new_sl": decision.new_sl,
                            "llm_new_tp": decision.new_tp,
                        },
                    )

            # ── Step 7: MT5 action ─────────────────────────────────────────────
            executor = MT5Executor(bridge)
            dry_run = account.paper_trade_enabled

            if final_action == "CLOSE":
                t0 = time.monotonic()
                mt5_result = await executor.close_position(
                    ticket=trade.ticket,
                    symbol=symbol,
                    volume=trade.volume,
                    dry_run=dry_run,
                )
                await tracer.record(
                    "mt5_close",
                    status="ok" if mt5_result.success else "error",
                    output_data={"success": mt5_result.success, "ticket": mt5_result.ticket},
                    error=mt5_result.error,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                logger.info(
                    "Maintenance CLOSE | account=%d ticket=%d symbol=%s success=%s",
                    account.id, trade.ticket, symbol, mt5_result.success,
                )

            elif final_action == "MODIFY" and decision.new_sl is not None and decision.new_tp is not None:
                t0 = time.monotonic()
                mt5_result = await executor.modify_order(
                    ticket=trade.ticket,
                    symbol=symbol,
                    new_sl=decision.new_sl,
                    new_tp=decision.new_tp,
                    dry_run=dry_run,
                )
                if mt5_result.success:
                    # Update trade row with new SL/TP
                    trade.stop_loss = decision.new_sl
                    trade.take_profit = decision.new_tp
                    await db.commit()
                await tracer.record(
                    "mt5_modify",
                    status="ok" if mt5_result.success else "error",
                    output_data={
                        "success": mt5_result.success,
                        "new_sl": decision.new_sl,
                        "new_tp": decision.new_tp,
                    },
                    error=mt5_result.error,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                logger.info(
                    "Maintenance MODIFY | account=%d ticket=%d symbol=%s "
                    "sl=%.5f tp=%.5f success=%s",
                    account.id, trade.ticket, symbol,
                    decision.new_sl, decision.new_tp, mt5_result.success,
                )

            else:
                await tracer.record(
                    "maintenance_hold",
                    output_data={
                        "rationale": decision.rationale,
                        "confidence": decision.confidence,
                        "constraint_reason": constraint_reason,
                    },
                )
                logger.info(
                    "Maintenance HOLD | account=%d ticket=%d symbol=%s",
                    account.id, trade.ticket, symbol,
                )

            tracer.finalize(status="completed", final_action=final_action)
            return final_action
```

---

## Task 8: Register Maintenance Job in Scheduler

**Files:**
- Modify: `backend/services/scheduler.py`

**Step 1: Update start_scheduler() to add the maintenance job**

In `backend/services/scheduler.py`, update the `start_scheduler()` function.
After the HMM retrain job registration (before `_scheduler.start()`), add:

```python
    # Position maintenance sweep — runs every maintenance_interval_minutes
    from services.position_maintenance import PositionMaintenanceService
    _maintenance_service = PositionMaintenanceService()

    async def _run_maintenance_sweep() -> None:
        async with AsyncSessionLocal() as db:
            await _maintenance_service.run_maintenance_sweep(db)

    _scheduler.add_job(
        _run_maintenance_sweep,
        trigger=IntervalTrigger(minutes=settings.maintenance_interval_minutes),
        id="position_maintenance_sweep",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info(
        "Position maintenance job registered | interval=%dmin enabled=%s",
        settings.maintenance_interval_minutes,
        settings.maintenance_task_enabled,
    )
```

Also add the import at the top of `start_scheduler()`:
```python
    from core.config import settings
```

---

## Task 9: Settings API — expose maintenance settings + 3 new LLM task roles

**Files:**
- Modify: `backend/api/routes/settings.py`

**Step 1: Update _VALID_TASKS**

Change:
```python
_VALID_TASKS = {"market_analysis", "vision", "execution_decision"}
```
To:
```python
_VALID_TASKS = {
    "market_analysis", "vision", "execution_decision",
    "maintenance_technical", "maintenance_sentiment", "maintenance_decision",
}
```

**Step 2: Update get_assignments() to include maintenance roles**

Change the task list in `get_assignments()`:
```python
    for task in [
        "market_analysis", "vision", "execution_decision",
        "maintenance_technical", "maintenance_sentiment", "maintenance_decision",
    ]:
```

**Step 3: Add GlobalSettings endpoint**

Add a `GlobalSettings` schema and two new routes at the bottom:

```python
# ── Global Settings ────────────────────────────────────────────────────────────

class GlobalSettings(BaseModel):
    maintenance_interval_minutes: int
    maintenance_task_enabled: bool
    llm_confidence_threshold: float
    news_enabled: bool


class GlobalSettingsPatch(BaseModel):
    maintenance_interval_minutes: int | None = None
    maintenance_task_enabled: bool | None = None
    llm_confidence_threshold: float | None = None
    news_enabled: bool | None = None


@router.get("/global", response_model=GlobalSettings)
async def get_global_settings() -> GlobalSettings:
    """Return current global settings from config."""
    return GlobalSettings(
        maintenance_interval_minutes=settings.maintenance_interval_minutes,
        maintenance_task_enabled=settings.maintenance_task_enabled,
        llm_confidence_threshold=settings.llm_confidence_threshold,
        news_enabled=settings.news_enabled,
    )


@router.patch("/global", response_model=GlobalSettings)
async def patch_global_settings(body: GlobalSettingsPatch) -> GlobalSettings:
    """Update in-memory settings (runtime only — restart to make permanent)."""
    if body.maintenance_interval_minutes is not None:
        if body.maintenance_interval_minutes < 1:
            raise HTTPException(status_code=422, detail="maintenance_interval_minutes must be >= 1")
        settings.maintenance_interval_minutes = body.maintenance_interval_minutes
    if body.maintenance_task_enabled is not None:
        settings.maintenance_task_enabled = body.maintenance_task_enabled
    if body.llm_confidence_threshold is not None:
        if not 0.0 <= body.llm_confidence_threshold <= 1.0:
            raise HTTPException(status_code=422, detail="llm_confidence_threshold must be 0.0-1.0")
        settings.llm_confidence_threshold = body.llm_confidence_threshold
    if body.news_enabled is not None:
        settings.news_enabled = body.news_enabled
    logger.info("Global settings updated | %s", body.model_dump(exclude_none=True))
    return await get_global_settings()
```

**Step 4: Add strategy maintenance toggle to strategies route**

Open `backend/api/routes/strategies.py`. Find the PATCH route and add `maintenance_enabled` to the patch schema and update logic.

Look for the strategy update schema (e.g., `StrategyUpdate` or similar Pydantic model) and add:
```python
    maintenance_enabled: bool | None = None
```

In the patch handler, add the field update:
```python
    if body.maintenance_enabled is not None:
        strategy.maintenance_enabled = body.maintenance_enabled
```

**Step 5: Add trade maintenance toggle to trades route**

Open `backend/api/routes/trades.py`. Add a PATCH route:

```python
class TradePatch(BaseModel):
    maintenance_enabled: bool | None = None


@router.patch("/{trade_id}", response_model=dict)
async def patch_trade(
    trade_id: int,
    body: TradePatch,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update trade properties (currently: maintenance_enabled toggle)."""
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if body.maintenance_enabled is not None:
        trade.maintenance_enabled = body.maintenance_enabled
    await db.commit()
    return {"id": trade_id, "maintenance_enabled": trade.maintenance_enabled}
```

Also add the Trade import if not already present:
```python
from db.models import Trade
```

---

## Task 10: Frontend — Types update

**Files:**
- Modify: `frontend/src/types/trading.ts`

**Step 1: Add maintenance_enabled to Trade type**

In `frontend/src/types/trading.ts`, update the `Trade` interface:
```typescript
export interface Trade {
  id: number;
  account_id: number;
  ticket: number;
  symbol: string;
  direction: "BUY" | "SELL";
  volume: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  close_price: number | null;
  profit: number | null;
  opened_at: string;
  closed_at: string | null;
  source: "ai" | "manual";
  order_type?: "market" | "limit" | "stop";
  order_status?: "pending" | "filled" | "cancelled" | "expired";
  maintenance_enabled?: boolean;   // ← add this
}
```

**Step 2: Add PipelineRunSummary task_type field**

Find `PipelineRunSummary` in `frontend/src/types/trading.ts` (or `frontend/src/lib/api.ts`) and add:
```typescript
  task_type?: "signal" | "maintenance";
```

**Step 3: Add GlobalSettings type**

```typescript
export interface GlobalSettings {
  maintenance_interval_minutes: number;
  maintenance_task_enabled: boolean;
  llm_confidence_threshold: number;
  news_enabled: boolean;
}
```

---

## Task 11: Frontend — API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Step 1: Add maintenance settings endpoints**

In `frontend/src/lib/api.ts`, add a `settingsApi` section (or add to existing):

```typescript
export const settingsApi = {
  getGlobal: () =>
    apiRequest<GlobalSettings>("/settings/global"),

  patchGlobal: (body: Partial<GlobalSettings>) =>
    apiRequest<GlobalSettings>("/settings/global", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  getAssignments: () =>
    apiRequest<TaskAssignment[]>("/settings/llm/assignments"),
};

export const tradesApi = {
  // ... existing trade API methods ...
  patchTrade: (tradeId: number, body: { maintenance_enabled?: boolean }) =>
    apiRequest<{ id: number; maintenance_enabled: boolean }>(
      `/trades/${tradeId}`,
      { method: "PATCH", body: JSON.stringify(body) }
    ),
};
```

---

## Task 12: Frontend — Settings page (maintenance interval + toggle)

**Files:**
- Modify: `frontend/src/app/settings/page.tsx`

**Step 1: Add maintenance section**

Read the current settings page to understand its structure, then add a "Position Maintenance" section with:

1. A toggle switch for `maintenance_task_enabled`
2. A number input for `maintenance_interval_minutes` (min=1, step=5)

Pattern — use existing settings patterns on the page. The section should:
- Fetch current settings on mount via `settingsApi.getGlobal()`
- Debounce save with `settingsApi.patchGlobal()`
- Show a toast on success

Example JSX structure to add:
```tsx
<Card>
  <CardHeader>
    <CardTitle>Position Maintenance</CardTitle>
    <CardDescription>
      Scheduled AI review of open positions. The LLM analyzes technical
      conditions and sentiment to suggest hold, close, or modify actions.
    </CardDescription>
  </CardHeader>
  <CardContent className="space-y-4">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium">Enable Maintenance Task</p>
        <p className="text-xs text-muted-foreground">
          Globally enable or disable the scheduled maintenance sweep
        </p>
      </div>
      <Switch
        checked={maintenanceEnabled}
        onCheckedChange={(v) => handleToggle("maintenance_task_enabled", v)}
      />
    </div>
    <div className="space-y-1.5">
      <Label htmlFor="maintenance-interval">Maintenance Interval (minutes)</Label>
      <Input
        id="maintenance-interval"
        type="number"
        min={1}
        step={5}
        value={maintenanceInterval}
        onChange={(e) => setMaintenanceInterval(Number(e.target.value))}
        onBlur={() => handleSaveInterval()}
        className="w-32"
      />
      <p className="text-xs text-muted-foreground">
        How often the maintenance sweep runs (default: 60 minutes)
      </p>
    </div>
  </CardContent>
</Card>
```

---

## Task 13: Frontend — Strategy card maintenance toggle

**Files:**
- Modify (or find): `frontend/src/app/strategies/page.tsx` or `frontend/src/app/strategies/[id]/page.tsx`
- Or the strategy card component

**Step 1: Find the strategy detail/edit form**

The strategy edit page is at `frontend/src/app/strategies/[id]/edit/page.tsx`. Read this file, then add a `maintenance_enabled` toggle to the form.

Look for the strategy update call (PATCH to `/strategies/{id}`) and add `maintenance_enabled` to the payload.

Add a toggle in the form:
```tsx
<div className="flex items-center justify-between py-2">
  <div>
    <p className="text-sm font-medium">Position Maintenance</p>
    <p className="text-xs text-muted-foreground">
      Allow AI to review and manage positions opened by this strategy
    </p>
  </div>
  <Switch
    checked={formValues.maintenance_enabled ?? true}
    onCheckedChange={(v) =>
      setFormValues((prev) => ({ ...prev, maintenance_enabled: v }))
    }
  />
</div>
```

---

## Task 14: Frontend — Pipeline Logs task_type filter

**Files:**
- Modify: `frontend/src/components/logs/pipeline-runs-list.tsx`

**Step 1: Add task_type filter chip**

Read `frontend/src/components/logs/pipeline-runs-list.tsx`.

Add a new filter state:
```typescript
const [taskTypeFilter, setTaskTypeFilter] = useState<"all" | "signal" | "maintenance">("all");
```

Add a filter selector (after the existing status filter):
```tsx
<Select value={taskTypeFilter} onValueChange={(v) => setTaskTypeFilter(v as typeof taskTypeFilter)}>
  <SelectTrigger className="h-7 text-xs w-32">
    <SelectValue />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="all">All Types</SelectItem>
    <SelectItem value="signal">Signal</SelectItem>
    <SelectItem value="maintenance">Maintenance</SelectItem>
  </SelectContent>
</Select>
```

Pass `task_type` to the API call:
```typescript
const data = await logsApi.listRuns({
  account_id: activeAccountId ?? undefined,
  symbol: symbolFilter.trim() || undefined,
  status: statusFilter !== "all" ? statusFilter : undefined,
  task_type: taskTypeFilter !== "all" ? taskTypeFilter : undefined,
  limit: 100,
});
```

**Step 2: Add task_type to API**

In `frontend/src/lib/api.ts`, update `logsApi.listRuns` to accept `task_type?`:
```typescript
  listRuns: (params: {
    account_id?: number;
    symbol?: string;
    status?: string;
    task_type?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    // ... existing params ...
    if (params.task_type) q.set("task_type", params.task_type);
    return apiRequest<PipelineRunSummary[]>(`/pipeline/runs?${q}`);
  },
```

**Step 3: Update backend pipeline route to support task_type filter**

Open `backend/api/routes/pipeline.py`. In the runs list query, add optional `task_type` filter:
```python
@router.get("/runs", response_model=list[PipelineRunSummary])
async def list_runs(
    account_id: int | None = None,
    symbol: str | None = None,
    status: str | None = None,
    task_type: str | None = None,   # ← add
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[PipelineRunSummary]:
    q = select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(limit)
    if account_id:
        q = q.where(PipelineRun.account_id == account_id)
    if symbol:
        q = q.where(PipelineRun.symbol == symbol)
    if status:
        q = q.where(PipelineRun.status == status)
    if task_type:          # ← add
        q = q.where(PipelineRun.task_type == task_type)
    # ... rest unchanged
```

Also update the `PipelineRunSummary` response schema to include `task_type`:
```python
class PipelineRunSummary(BaseModel):
    # ... existing fields ...
    task_type: str = "signal"
```

---

## Task 15: Trades page — per-trade maintenance toggle

**Files:**
- Modify: `frontend/src/app/trades/page.tsx`

**Step 1: Read the trades page and add the toggle**

Read `frontend/src/app/trades/page.tsx`. Find the table where trades are listed.

Add a "Maint." column with a small `Switch` component per row:
```tsx
<Switch
  checked={trade.maintenance_enabled ?? true}
  onCheckedChange={async (checked) => {
    await tradesApi.patchTrade(trade.id, { maintenance_enabled: checked });
    // refresh trade list
  }}
  className="scale-75"
/>
```

---

## Verification

**Step 1: Run backend tests**

```bash
cd backend
uv run pytest -v tests/
```

Expected: all existing tests pass.

**Step 2: Run migrations on a clean DB**

```bash
uv run alembic downgrade base
uv run alembic upgrade head
```

Expected: no errors.

**Step 3: Start backend and verify maintenance job registered**

```bash
uv run uvicorn main:app --reload --port 8000
```

Look for in logs:
```
INFO  scheduler: Position maintenance job registered | interval=60min enabled=True
INFO  scheduler: Scheduler started with N jobs
```

**Step 4: Verify API endpoints**

```bash
curl http://localhost:8000/api/v1/settings/global
```
Expected: `{"maintenance_interval_minutes":60,"maintenance_task_enabled":true,...}`

```bash
curl http://localhost:8000/api/v1/settings/llm/assignments
```
Expected: response includes `maintenance_technical`, `maintenance_sentiment`, `maintenance_decision` tasks.

**Step 5: Start frontend and verify UI**

```bash
cd frontend
npm run dev
```

- Navigate to `/settings` → verify "Position Maintenance" section with toggle + interval input
- Navigate to `/strategies/{id}/edit` → verify "Position Maintenance" toggle in form
- Navigate to `/trades` → verify "Maint." column with toggles
- Navigate to `/logs` → verify "All Types | Signal | Maintenance" filter chips
