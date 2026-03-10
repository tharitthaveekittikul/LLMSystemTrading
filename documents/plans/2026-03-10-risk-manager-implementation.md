# Risk Manager Overhaul Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded risk checks with toggleable rules (drawdown, position limit, rate limit, hedging) stored in a DB-backed `risk_settings` table and configurable via the Settings page.

**Architecture:** New singleton `risk_settings` DB table stores all rule toggles and thresholds. `risk_manager.py` gains a `RiskConfig` dataclass + 4 check functions (3 pure, 1 async). Callers (`executor.py`, `equity_poller.py`) load `RiskConfig` from DB before each check. A new `GET/PATCH /settings/risk` endpoint and a frontend "Risk Manager" section complete the feature.

**Tech Stack:** SQLAlchemy (async), Alembic, FastAPI/Pydantic v2, Next.js / TypeScript, shadcn/ui

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/db/models.py` | Modify | Add `RiskSettings` SQLAlchemy model |
| `backend/alembic/versions/b7e4f9a2c1d8_add_risk_settings_table.py` | Create | Migration: create table + seed defaults |
| `backend/services/risk_manager.py` | Rewrite | `RiskConfig` dataclass, 4 check functions, `load_risk_config()` |
| `backend/tests/test_risk_manager.py` | Rewrite | Tests for all 4 rules (including async rate-limit) |
| `backend/mt5/executor.py` | Modify | Load `RiskConfig` from DB; call all 4 checks in `place_order` |
| `backend/services/equity_poller.py` | Modify | Load `RiskConfig` from DB; pass to `check_drawdown` |
| `backend/api/routes/settings.py` | Modify | Add `GET/PATCH /settings/risk` endpoints + Pydantic schemas |
| `frontend/src/types/trading.ts` | Modify | Add `RiskSettings` interface |
| `frontend/src/lib/api/settings.ts` | Modify | Add `getRisk()` + `patchRisk()` methods |
| `frontend/src/app/settings/page.tsx` | Modify | Add `RiskManagerSection` component |

---

## Chunk 1: DB Model + Alembic Migration

### Task 1: Add RiskSettings SQLAlchemy model

**Files:**
- Modify: `backend/db/models.py` (append after `TaskLLMAssignment` class, before `BacktestRun`)

- [ ] **Step 1: Add the model**

  Append after the `TaskLLMAssignment` class (after line 268, before the `BacktestRun` class):

  ```python
  class RiskSettings(Base):
      __tablename__ = "risk_settings"

      id: Mapped[int] = mapped_column(Integer, primary_key=True)
      # Rule 1: Drawdown check
      drawdown_check_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
      max_drawdown_pct: Mapped[float] = mapped_column(Float, default=10.0)
      # Rule 2: Position limit
      position_limit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
      max_open_positions: Mapped[int] = mapped_column(Integer, default=5)
      # Rule 3: Rate limit per symbol
      rate_limit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
      rate_limit_max_trades: Mapped[int] = mapped_column(Integer, default=3)
      rate_limit_window_hours: Mapped[float] = mapped_column(Float, default=4.0)
      # Rule 4: Hedging
      hedging_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
      updated_at: Mapped[datetime] = mapped_column(
          DateTime(timezone=True),
          default=lambda: datetime.now(UTC),
          onupdate=lambda: datetime.now(UTC),
      )
  ```

- [ ] **Step 2: Verify model is importable**

  Run from `backend/`:
  ```bash
  uv run python -c "from db.models import RiskSettings; print('OK')"
  ```
  Expected: `OK`

### Task 2: Alembic migration

**Files:**
- Create: `backend/alembic/versions/b7e4f9a2c1d8_add_risk_settings_table.py`

- [ ] **Step 1: Create migration file**

  ```python
  """add_risk_settings_table

  Revision ID: b7e4f9a2c1d8
  Revises: a8f3c2e91b05
  Create Date: 2026-03-10 00:00:00.000000
  """
  from typing import Sequence, Union

  from alembic import op
  import sqlalchemy as sa


  revision: str = 'b7e4f9a2c1d8'
  down_revision: Union[str, Sequence[str], None] = 'a8f3c2e91b05'
  branch_labels: Union[str, Sequence[str], None] = None
  depends_on: Union[str, Sequence[str], None] = None


  def upgrade() -> None:
      op.create_table(
          'risk_settings',
          sa.Column('id', sa.Integer(), primary_key=True),
          sa.Column('drawdown_check_enabled', sa.Boolean(), nullable=False, server_default='false'),
          sa.Column('max_drawdown_pct', sa.Float(), nullable=False, server_default='10.0'),
          sa.Column('position_limit_enabled', sa.Boolean(), nullable=False, server_default='false'),
          sa.Column('max_open_positions', sa.Integer(), nullable=False, server_default='5'),
          sa.Column('rate_limit_enabled', sa.Boolean(), nullable=False, server_default='false'),
          sa.Column('rate_limit_max_trades', sa.Integer(), nullable=False, server_default='3'),
          sa.Column('rate_limit_window_hours', sa.Float(), nullable=False, server_default='4.0'),
          sa.Column('hedging_allowed', sa.Boolean(), nullable=False, server_default='true'),
          sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                    server_default=sa.text('NOW()')),
      )
      # Seed singleton default row
      op.execute(
          "INSERT INTO risk_settings (id, drawdown_check_enabled, max_drawdown_pct, "
          "position_limit_enabled, max_open_positions, rate_limit_enabled, "
          "rate_limit_max_trades, rate_limit_window_hours, hedging_allowed, updated_at) "
          "VALUES (1, false, 10.0, false, 5, false, 3, 4.0, true, NOW())"
      )


  def downgrade() -> None:
      op.drop_table('risk_settings')
  ```

- [ ] **Step 2: Run migration**

  ```bash
  cd backend && uv run alembic upgrade head
  ```
  Expected: `Running upgrade a8f3c2e91b05 -> b7e4f9a2c1d8, add_risk_settings_table`

- [ ] **Step 3: Verify row was seeded**

  ```bash
  uv run python -c "
  import asyncio
  from db.postgres import AsyncSessionLocal
  from db.models import RiskSettings
  from sqlalchemy import select
  async def check():
      async with AsyncSessionLocal() as db:
          row = (await db.execute(select(RiskSettings).where(RiskSettings.id == 1))).scalar_one()
          print(f'hedging_allowed={row.hedging_allowed}, drawdown_enabled={row.drawdown_check_enabled}')
  asyncio.run(check())
  "
  ```
  Expected: `hedging_allowed=True, drawdown_enabled=False`

- [ ] **Step 4: Commit**

  ```bash
  git add backend/db/models.py backend/alembic/versions/b7e4f9a2c1d8_add_risk_settings_table.py
  git commit -m "feat(db): add risk_settings table with singleton row"
  ```

---

## Chunk 2: Risk Manager Rewrite

### Task 3: Write tests first (TDD)

**Files:**
- Rewrite: `backend/tests/test_risk_manager.py`

- [ ] **Step 1: Replace test file content**

  ```python
  """Tests for risk_manager — all 4 rules."""
  from datetime import UTC, datetime, timedelta
  from unittest.mock import AsyncMock, MagicMock, patch

  import pytest

  from services.risk_manager import (
      RiskConfig,
      check_drawdown,
      check_hedging,
      check_position_limit,
      check_rate_limit,
  )


  # ── Helpers ────────────────────────────────────────────────────────────────

  def _cfg(**kwargs) -> RiskConfig:
      """Build a RiskConfig with all rules enabled and sensible defaults."""
      defaults = dict(
          drawdown_check_enabled=True,
          max_drawdown_pct=10.0,
          position_limit_enabled=True,
          max_open_positions=5,
          rate_limit_enabled=True,
          rate_limit_max_trades=3,
          rate_limit_window_hours=4.0,
          hedging_allowed=False,
      )
      defaults.update(kwargs)
      return RiskConfig(**defaults)


  def _pos(symbol: str = "EURUSD", pos_type: int = 0, ticket: int = 1) -> dict:
      """Build a fake MT5 position dict. type 0=BUY, 1=SELL."""
      return {"ticket": ticket, "symbol": symbol, "type": pos_type}


  # ── check_drawdown ─────────────────────────────────────────────────────────

  def test_drawdown_disabled_always_passes():
      cfg = _cfg(drawdown_check_enabled=False, max_drawdown_pct=0.1)
      exceeded, reason = check_drawdown(1.0, 10000.0, cfg)
      assert exceeded is False
      assert reason == ""


  def test_drawdown_not_exceeded():
      exceeded, reason = check_drawdown(equity=9500.0, balance=10000.0, cfg=_cfg())
      assert exceeded is False


  def test_drawdown_exactly_at_limit():
      exceeded, reason = check_drawdown(equity=9000.0, balance=10000.0, cfg=_cfg(max_drawdown_pct=10.0))
      assert exceeded is True
      assert "10.00%" in reason


  def test_drawdown_zero_balance_safe():
      exceeded, _ = check_drawdown(equity=0.0, balance=0.0, cfg=_cfg())
      assert exceeded is False


  # ── check_position_limit ───────────────────────────────────────────────────

  def test_position_limit_disabled_always_passes():
      positions = [_pos() for _ in range(100)]
      exceeded, _ = check_position_limit(positions, _cfg(position_limit_enabled=False))
      assert exceeded is False


  def test_position_limit_not_exceeded():
      positions = [_pos(ticket=i) for i in range(3)]
      exceeded, _ = check_position_limit(positions, _cfg(max_open_positions=5))
      assert exceeded is False


  def test_position_limit_at_max():
      positions = [_pos(ticket=i) for i in range(5)]
      exceeded, reason = check_position_limit(positions, _cfg(max_open_positions=5))
      assert exceeded is True
      assert "5/5" in reason


  # ── check_hedging ──────────────────────────────────────────────────────────

  def test_hedging_allowed_always_passes():
      positions = [_pos("EURUSD", pos_type=1)]  # existing SELL
      exceeded, _ = check_hedging("EURUSD", "BUY", positions, _cfg(hedging_allowed=True))
      assert exceeded is False


  def test_hedging_disabled_rejects_opposite_side():
      positions = [_pos("EURUSD", pos_type=1)]  # existing SELL
      exceeded, reason = check_hedging("EURUSD", "BUY", positions, _cfg(hedging_allowed=False))
      assert exceeded is True
      assert "EURUSD" in reason


  def test_hedging_disabled_allows_same_side():
      positions = [_pos("EURUSD", pos_type=0)]  # existing BUY
      exceeded, _ = check_hedging("EURUSD", "BUY", positions, _cfg(hedging_allowed=False))
      assert exceeded is False


  def test_hedging_disabled_different_symbol_passes():
      positions = [_pos("GBPUSD", pos_type=1)]  # SELL on different symbol
      exceeded, _ = check_hedging("EURUSD", "BUY", positions, _cfg(hedging_allowed=False))
      assert exceeded is False


  def test_hedging_sell_blocked_by_existing_buy():
      positions = [_pos("EURUSD", pos_type=0)]  # existing BUY
      exceeded, reason = check_hedging("EURUSD", "SELL", positions, _cfg(hedging_allowed=False))
      assert exceeded is True


  # ── check_rate_limit ───────────────────────────────────────────────────────

  @pytest.mark.asyncio
  async def test_rate_limit_disabled_always_passes():
      mock_db = AsyncMock()
      exceeded, _ = await check_rate_limit("EURUSD", _cfg(rate_limit_enabled=False), mock_db)
      assert exceeded is False
      mock_db.execute.assert_not_called()


  @pytest.mark.asyncio
  async def test_rate_limit_not_exceeded():
      mock_db = AsyncMock()
      mock_result = MagicMock()
      mock_result.scalar.return_value = 2
      mock_db.execute.return_value = mock_result

      exceeded, _ = await check_rate_limit(
          "EURUSD", _cfg(rate_limit_max_trades=3, rate_limit_window_hours=4.0), mock_db
      )
      assert exceeded is False


  @pytest.mark.asyncio
  async def test_rate_limit_at_max():
      mock_db = AsyncMock()
      mock_result = MagicMock()
      mock_result.scalar.return_value = 3
      mock_db.execute.return_value = mock_result

      exceeded, reason = await check_rate_limit(
          "EURUSD", _cfg(rate_limit_max_trades=3, rate_limit_window_hours=4.0), mock_db
      )
      assert exceeded is True
      assert "3/3" in reason
      assert "EURUSD" in reason


  @pytest.mark.asyncio
  async def test_rate_limit_queries_correct_symbol():
      """Verify DB is queried (symbol filtering is done in SQL)."""
      mock_db = AsyncMock()
      mock_result = MagicMock()
      mock_result.scalar.return_value = 0
      mock_db.execute.return_value = mock_result

      await check_rate_limit("XAUUSD", _cfg(), mock_db)
      mock_db.execute.assert_called_once()
  ```

- [ ] **Step 2: Run tests — expect ImportError (functions don't exist yet)**

  ```bash
  cd backend && uv run pytest tests/test_risk_manager.py -v 2>&1 | head -20
  ```
  Expected: `ImportError: cannot import name 'RiskConfig'` (or similar)

### Task 4: Implement the new risk_manager.py

**Files:**
- Rewrite: `backend/services/risk_manager.py`

- [ ] **Step 1: Replace risk_manager.py**

  ```python
  """Runtime risk checks — toggleable rules with no writes or external I/O.

  All pure check functions take a RiskConfig dataclass (loaded by callers).
  check_rate_limit is async because it queries the trades table.
  load_risk_config() is provided as a convenience loader for callers.
  """
  import logging
  from dataclasses import dataclass, field
  from datetime import UTC, datetime, timedelta
  from typing import Any

  from sqlalchemy import func, select
  from sqlalchemy.ext.asyncio import AsyncSession

  logger = logging.getLogger(__name__)


  @dataclass
  class RiskConfig:
      """Snapshot of risk_settings DB row. Passed to all check functions."""
      drawdown_check_enabled: bool = False
      max_drawdown_pct: float = 10.0
      position_limit_enabled: bool = False
      max_open_positions: int = 5
      rate_limit_enabled: bool = False
      rate_limit_max_trades: int = 3
      rate_limit_window_hours: float = 4.0
      hedging_allowed: bool = True


  async def load_risk_config(db: AsyncSession) -> RiskConfig:
      """Load singleton risk_settings row from DB. Returns safe defaults if row missing."""
      from db.models import RiskSettings  # local import — avoids circular at module load

      row = (
          await db.execute(select(RiskSettings).where(RiskSettings.id == 1))
      ).scalar_one_or_none()
      if not row:
          logger.warning("risk_settings row not found — using safe defaults (all checks disabled)")
          return RiskConfig()
      return RiskConfig(
          drawdown_check_enabled=row.drawdown_check_enabled,
          max_drawdown_pct=row.max_drawdown_pct,
          position_limit_enabled=row.position_limit_enabled,
          max_open_positions=row.max_open_positions,
          rate_limit_enabled=row.rate_limit_enabled,
          rate_limit_max_trades=row.rate_limit_max_trades,
          rate_limit_window_hours=row.rate_limit_window_hours,
          hedging_allowed=row.hedging_allowed,
      )


  # ── Pure check functions (no I/O) ──────────────────────────────────────────

  def check_drawdown(equity: float, balance: float, cfg: RiskConfig) -> tuple[bool, str]:
      """Return (exceeded, reason). True → kill switch should fire."""
      if not cfg.drawdown_check_enabled:
          return False, ""
      if balance <= 0:
          return False, ""
      drawdown_pct = (balance - equity) / balance * 100
      if drawdown_pct >= cfg.max_drawdown_pct:
          reason = (
              f"Max drawdown exceeded: {drawdown_pct:.2f}% >= {cfg.max_drawdown_pct:.1f}% "
              f"(equity={equity:.2f}, balance={balance:.2f})"
          )
          logger.warning(reason)
          return True, reason
      return False, ""


  def check_position_limit(
      positions: list[dict[str, Any]], cfg: RiskConfig
  ) -> tuple[bool, str]:
      """Return (exceeded, reason). True → order should be rejected."""
      if not cfg.position_limit_enabled:
          return False, ""
      count = len(positions)
      if count >= cfg.max_open_positions:
          reason = f"Position limit reached: {count}/{cfg.max_open_positions} open positions"
          logger.warning(reason)
          return True, reason
      return False, ""


  def check_hedging(
      symbol: str,
      direction: str,
      positions: list[dict[str, Any]],
      cfg: RiskConfig,
  ) -> tuple[bool, str]:
      """Return (exceeded, reason). True → order rejected (hedging disabled).

      direction: "BUY" or "SELL" (the new trade's underlying direction).
      position type: 0=BUY, 1=SELL (MT5 convention).
      """
      if cfg.hedging_allowed:
          return False, ""
      # Opposite MT5 type for the incoming direction
      opposite_type = 1 if direction == "BUY" else 0
      opposite_label = "SELL" if direction == "BUY" else "BUY"
      for pos in positions:
          if pos.get("symbol") == symbol and pos.get("type") == opposite_type:
              reason = (
                  f"Hedging disabled: opposite {opposite_label} position already "
                  f"open on {symbol} (ticket={pos.get('ticket')})"
              )
              logger.warning(reason)
              return True, reason
      return False, ""


  async def check_rate_limit(
      symbol: str, cfg: RiskConfig, db: AsyncSession
  ) -> tuple[bool, str]:
      """Return (exceeded, reason). True → order rejected (rate limit hit).

      Counts trades opened on `symbol` within the rolling window.
      Queries the trades table — hedges count toward the limit.
      """
      if not cfg.rate_limit_enabled:
          return False, ""
      from db.models import Trade  # local import — avoids circular at module load

      cutoff = datetime.now(UTC) - timedelta(hours=cfg.rate_limit_window_hours)
      result = await db.execute(
          select(func.count()).select_from(Trade).where(
              Trade.symbol == symbol,
              Trade.opened_at >= cutoff,
          )
      )
      count: int = result.scalar() or 0
      if count >= cfg.rate_limit_max_trades:
          reason = (
              f"Rate limit hit: {count}/{cfg.rate_limit_max_trades} trades on {symbol} "
              f"in the last {cfg.rate_limit_window_hours:.1f}h"
          )
          logger.warning(reason)
          return True, reason
      return False, ""
  ```

- [ ] **Step 2: Run all risk manager tests — expect PASS**

  ```bash
  cd backend && uv run pytest tests/test_risk_manager.py -v
  ```
  Expected: All tests `PASSED`

- [ ] **Step 3: Commit**

  ```bash
  git add backend/services/risk_manager.py backend/tests/test_risk_manager.py
  git commit -m "feat(risk): rewrite risk_manager with toggleable RiskConfig rules"
  ```

---

## Chunk 3: Update Callers

### Task 5: Update executor.py

**Files:**
- Modify: `backend/mt5/executor.py`

The `place_order` method currently calls `exceeds_position_limit` using `settings.max_open_positions`. Replace with all 4 risk checks loaded from DB.

- [ ] **Step 1: Update imports at top of executor.py** (lines 14-16)

  Replace:
  ```python
  from services.risk_manager import exceeds_position_limit
  ```
  With:
  ```python
  from services.risk_manager import check_drawdown, check_hedging, check_position_limit, check_rate_limit, load_risk_config
  ```

- [ ] **Step 2: Replace the "Position count gate" block in `place_order`** (lines 95–108)

  Replace the block from `# ── Position count gate` through `return OrderResult(success=False, error=reason)` with:

  ```python
  # ── Risk checks (position limit, hedging, rate limit) ─────────────────────
  try:
      open_positions = await self._bridge.get_positions()
  except Exception as exc:
      logger.warning("Could not fetch positions for risk check: %s", exc)
      open_positions = []

  from db.postgres import AsyncSessionLocal  # local import — avoids circular
  async with AsyncSessionLocal() as _db:
      risk_cfg = await load_risk_config(_db)

      exceeded, reason = check_position_limit(open_positions, risk_cfg)
      if exceeded:
          logger.warning("Order rejected — %s | symbol=%s action=%s", reason, request.symbol, request.action)
          return OrderResult(success=False, error=reason)

      direction = "BUY" if request.action.startswith("BUY") else "SELL"
      exceeded, reason = check_hedging(request.symbol, direction, open_positions, risk_cfg)
      if exceeded:
          logger.warning("Order rejected — %s | symbol=%s action=%s", reason, request.symbol, request.action)
          return OrderResult(success=False, error=reason)

      exceeded, reason = await check_rate_limit(request.symbol, risk_cfg, _db)
      if exceeded:
          logger.warning("Order rejected — %s | symbol=%s action=%s", reason, request.symbol, request.action)
          return OrderResult(success=False, error=reason)
  ```

- [ ] **Step 3: Remove the now-unused `settings` import from executor.py**

  Check if `settings` is used anywhere else in the file. Search:
  ```bash
  grep -n "settings\." backend/mt5/executor.py
  ```
  If the only reference was `settings.max_open_positions` (now removed), remove the import line:
  ```python
  from core.config import settings
  ```

- [ ] **Step 4: Update existing executor tests to match new signature**

  In `backend/tests/test_risk_manager.py`, the existing executor tests (lines 64–111) mock `settings.max_open_positions`. These tests are no longer valid for the executor. The executor tests need to be updated to mock `load_risk_config`.

  In `test_risk_manager.py`, replace the executor test block (from `def _make_order()` to end of file) with:

  ```python
  # ── Executor integration tests ─────────────────────────────────────────────

  from mt5.executor import MT5Executor, OrderRequest


  def _make_order() -> OrderRequest:
      return OrderRequest(
          symbol="EURUSD",
          action="BUY",
          volume=0.1,
          entry_price=1.0850,
          stop_loss=1.0800,
          take_profit=1.0950,
      )


  def _risk_cfg_all_off() -> RiskConfig:
      return RiskConfig(
          position_limit_enabled=False,
          rate_limit_enabled=False,
          hedging_allowed=True,
      )


  @pytest.mark.asyncio
  async def test_executor_rejects_when_position_limit_hit():
      mock_bridge = AsyncMock()
      mock_bridge.get_positions.return_value = [{"ticket": i} for i in range(5)]

      cfg = RiskConfig(position_limit_enabled=True, max_open_positions=5,
                       rate_limit_enabled=False, hedging_allowed=True)
      executor = MT5Executor(bridge=mock_bridge)

      with patch("mt5.executor.kill_switch_active", return_value=False), \
           patch("mt5.executor.load_risk_config", new=AsyncMock(return_value=cfg)), \
           patch("mt5.executor.AsyncSessionLocal") as mock_session_cls:
          mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
          mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
          result = await executor.place_order(_make_order())

      assert result.success is False
      assert "Position limit" in result.error
      mock_bridge.send_order.assert_not_called()


  @pytest.mark.asyncio
  async def test_executor_dry_run_skips_bridge():
      mock_bridge = AsyncMock()
      mock_bridge.get_positions.return_value = []

      executor = MT5Executor(bridge=mock_bridge)

      with patch("mt5.executor.kill_switch_active", return_value=False), \
           patch("mt5.executor.load_risk_config", new=AsyncMock(return_value=_risk_cfg_all_off())), \
           patch("mt5.executor.AsyncSessionLocal") as mock_session_cls:
          mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
          mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
          result = await executor.place_order(_make_order(), dry_run=True)

      assert result.success is True
      assert result.ticket < 0
      mock_bridge.send_order.assert_not_called()


  @pytest.mark.asyncio
  async def test_executor_dry_run_close_does_not_call_bridge():
      mock_bridge = AsyncMock()
      executor = MT5Executor(bridge=mock_bridge)
      with patch("mt5.executor.kill_switch_active", return_value=False):
          result = await executor.close_position(ticket=12345, symbol="EURUSD", volume=0.1, dry_run=True)
      assert result.success is True
      mock_bridge.send_order.assert_not_called()
  ```

- [ ] **Step 5: Run all tests**

  ```bash
  cd backend && uv run pytest tests/test_risk_manager.py -v
  ```
  Expected: All tests `PASSED`

- [ ] **Step 6: Commit**

  ```bash
  git add backend/mt5/executor.py backend/tests/test_risk_manager.py
  git commit -m "feat(executor): load RiskConfig from DB, add hedging + rate-limit gates"
  ```

### Task 6: Update equity_poller.py

**Files:**
- Modify: `backend/services/equity_poller.py` (lines 15, 111–117)

- [ ] **Step 1: Update import at line 15**

  Replace:
  ```python
  from services.risk_manager import exceeds_drawdown_limit
  ```
  With:
  ```python
  from services.risk_manager import check_drawdown, load_risk_config
  ```

- [ ] **Step 2: Update the drawdown monitor block** (lines 111–117 in `_poll_account`)

  Replace:
  ```python
  # ── Drawdown monitor ─────────────────────────────────────────────────────
  from services.kill_switch import is_active, activate  # local import avoids circular

  if not is_active():
      exceeded, reason = exceeds_drawdown_limit(equity, balance, settings.max_drawdown_percent)
      if exceeded:
          await activate(reason, triggered_by="equity_poller")
  ```
  With:
  ```python
  # ── Drawdown monitor ─────────────────────────────────────────────────────
  from services.kill_switch import is_active, activate  # local import avoids circular
  from db.postgres import AsyncSessionLocal

  if not is_active():
      async with AsyncSessionLocal() as _db:
          risk_cfg = await load_risk_config(_db)
      exceeded, reason = check_drawdown(equity, balance, risk_cfg)
      if exceeded:
          await activate(reason, triggered_by="equity_poller")
  ```

- [ ] **Step 3: Remove unused `settings` import from equity_poller if no longer used**

  ```bash
  grep -n "settings\." backend/services/equity_poller.py
  ```
  If `settings` is still needed (e.g., `settings.mt5_path`), keep the import. Otherwise remove it.

- [ ] **Step 4: Run existing tests to confirm nothing broken**

  ```bash
  cd backend && uv run pytest -v
  ```
  Expected: All previously-passing tests still `PASSED`

- [ ] **Step 5: Commit**

  ```bash
  git add backend/services/equity_poller.py
  git commit -m "feat(poller): load RiskConfig from DB for toggleable drawdown check"
  ```

---

## Chunk 4: Settings API

### Task 7: Add GET/PATCH /settings/risk endpoints

**Files:**
- Modify: `backend/api/routes/settings.py` (append to end of file)

- [ ] **Step 1: Add Pydantic schemas and endpoints**

  Append after the last line of `settings.py` (after line 333):

  ```python
  # ── Risk Settings ──────────────────────────────────────────────────────────

  class RiskSettingsResponse(BaseModel):
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


  def _risk_row_to_response(row) -> RiskSettingsResponse:
      return RiskSettingsResponse(
          drawdown_check_enabled=row.drawdown_check_enabled,
          max_drawdown_pct=row.max_drawdown_pct,
          position_limit_enabled=row.position_limit_enabled,
          max_open_positions=row.max_open_positions,
          rate_limit_enabled=row.rate_limit_enabled,
          rate_limit_max_trades=row.rate_limit_max_trades,
          rate_limit_window_hours=row.rate_limit_window_hours,
          hedging_allowed=row.hedging_allowed,
      )


  @router.get("/risk", response_model=RiskSettingsResponse)
  async def get_risk_settings(db: AsyncSession = Depends(get_db)) -> RiskSettingsResponse:
      """Return current risk rule toggles and thresholds."""
      from db.models import RiskSettings
      row = (await db.execute(select(RiskSettings).where(RiskSettings.id == 1))).scalar_one_or_none()
      if not row:
          # Should never happen after migration, but handle gracefully
          from db.models import RiskSettings as RS
          row = RS(id=1)
          db.add(row)
          await db.commit()
          await db.refresh(row)
      return _risk_row_to_response(row)


  @router.patch("/risk", response_model=RiskSettingsResponse)
  async def patch_risk_settings(
      body: RiskSettingsPatch,
      db: AsyncSession = Depends(get_db),
  ) -> RiskSettingsResponse:
      """Update risk rule configuration (persisted to DB)."""
      from db.models import RiskSettings
      row = (await db.execute(select(RiskSettings).where(RiskSettings.id == 1))).scalar_one_or_none()
      if not row:
          row = RiskSettings(id=1)
          db.add(row)

      if body.drawdown_check_enabled is not None:
          row.drawdown_check_enabled = body.drawdown_check_enabled
      if body.max_drawdown_pct is not None:
          if not 0 < body.max_drawdown_pct <= 100:
              raise HTTPException(status_code=422, detail="max_drawdown_pct must be > 0 and <= 100")
          row.max_drawdown_pct = body.max_drawdown_pct
      if body.position_limit_enabled is not None:
          row.position_limit_enabled = body.position_limit_enabled
      if body.max_open_positions is not None:
          if body.max_open_positions < 1:
              raise HTTPException(status_code=422, detail="max_open_positions must be >= 1")
          row.max_open_positions = body.max_open_positions
      if body.rate_limit_enabled is not None:
          row.rate_limit_enabled = body.rate_limit_enabled
      if body.rate_limit_max_trades is not None:
          if body.rate_limit_max_trades < 1:
              raise HTTPException(status_code=422, detail="rate_limit_max_trades must be >= 1")
          row.rate_limit_max_trades = body.rate_limit_max_trades
      if body.rate_limit_window_hours is not None:
          if body.rate_limit_window_hours <= 0:
              raise HTTPException(status_code=422, detail="rate_limit_window_hours must be > 0")
          row.rate_limit_window_hours = body.rate_limit_window_hours
      if body.hedging_allowed is not None:
          row.hedging_allowed = body.hedging_allowed

      await db.commit()
      await db.refresh(row)
      logger.info("Risk settings updated | %s", body.model_dump(exclude_none=True))
      return _risk_row_to_response(row)
  ```

- [ ] **Step 2: Verify endpoints register correctly**

  ```bash
  cd backend && uv run python -c "
  from api.routes.settings import router
  routes = [r.path for r in router.routes]
  assert '/risk' in routes, f'Missing /risk, got: {routes}'
  print('Routes OK:', [r for r in routes if 'risk' in r])
  "
  ```
  Expected: `Routes OK: ['/risk', '/risk']`

- [ ] **Step 3: Quick smoke test against running backend** (optional if backend is running)

  ```bash
  curl -s http://localhost:8000/api/v1/settings/risk | python -m json.tool
  ```
  Expected: JSON with all 8 fields and defaults

- [ ] **Step 4: Commit**

  ```bash
  git add backend/api/routes/settings.py
  git commit -m "feat(api): add GET/PATCH /settings/risk endpoints"
  ```

---

## Chunk 5: Frontend

### Task 8: Add RiskSettings type and API methods

**Files:**
- Modify: `frontend/src/types/trading.ts` (append after `GlobalSettings`)
- Modify: `frontend/src/lib/api/settings.ts` (add 2 methods to `settingsApi`)

- [ ] **Step 1: Add RiskSettings interface to trading.ts**

  Append after the `GlobalSettings` interface (after line 525):

  ```typescript
  // ── Risk Settings ──────────────────────────────────────────────────────────

  export interface RiskSettings {
    drawdown_check_enabled: boolean;
    max_drawdown_pct: number;
    position_limit_enabled: boolean;
    max_open_positions: number;
    rate_limit_enabled: boolean;
    rate_limit_max_trades: number;
    rate_limit_window_hours: number;
    hedging_allowed: boolean;
  }
  ```

- [ ] **Step 2: Add API methods to settings.ts**

  At top of file, update the import:
  ```typescript
  import type { GlobalSettings, RiskSettings } from "@/types/trading";
  ```

  Append 2 methods to `settingsApi` object (after `patchGlobal`):

  ```typescript
  getRisk: () =>
    apiRequest<RiskSettings>("/settings/risk"),

  patchRisk: (body: Partial<RiskSettings>) =>
    apiRequest<RiskSettings>("/settings/risk", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  ```

- [ ] **Step 3: Verify TypeScript compiles**

  ```bash
  cd frontend && npx tsc --noEmit 2>&1 | head -20
  ```
  Expected: No errors

### Task 9: Add RiskManagerSection to Settings page

**Files:**
- Modify: `frontend/src/app/settings/page.tsx`

- [ ] **Step 1: Add import at top of settings page**

  After existing imports, add:
  ```typescript
  import type { RiskSettings } from "@/types/trading";
  import { settingsApi } from "@/lib/api/settings";
  ```
  (These may already be imported; check before adding)

- [ ] **Step 2: Add RiskManagerSection component**

  Add the following component function before the default export `SettingsPage` function in `page.tsx`:

  ```typescript
  function RiskManagerSection() {
    const [risk, setRisk] = useState<RiskSettings | null>(null);
    const [saving, setSaving] = useState(false);
    const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
      settingsApi.getRisk().then(setRisk).catch(console.error);
    }, []);

    const handleChange = (patch: Partial<RiskSettings>) => {
      if (!risk) return;
      const updated = { ...risk, ...patch };
      setRisk(updated);
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        setSaving(true);
        settingsApi
          .patchRisk(patch)
          .then(setRisk)
          .catch(console.error)
          .finally(() => setSaving(false));
      }, 800);
    };

    if (!risk) return <div className="text-sm text-muted-foreground">Loading risk settings…</div>;

    return (
      <div className="space-y-4">
        {/* Drawdown Check */}
        <div className="flex flex-col gap-3 rounded-lg border p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Drawdown Check</p>
              <p className="text-xs text-muted-foreground">
                Triggers kill switch when drawdown threshold is exceeded
              </p>
            </div>
            <Switch
              checked={risk.drawdown_check_enabled}
              onCheckedChange={(v) => handleChange({ drawdown_check_enabled: v })}
            />
          </div>
          {risk.drawdown_check_enabled && (
            <div className="flex items-center gap-2 pl-1">
              <Label className="w-40 text-xs">Max drawdown %</Label>
              <Input
                type="number"
                className="w-24 h-7 text-xs"
                value={risk.max_drawdown_pct}
                min={0.1}
                max={100}
                step={0.5}
                onChange={(e) => handleChange({ max_drawdown_pct: parseFloat(e.target.value) || 10 })}
              />
            </div>
          )}
        </div>

        {/* Position Limit */}
        <div className="flex flex-col gap-3 rounded-lg border p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Position Limit</p>
              <p className="text-xs text-muted-foreground">
                Reject new orders when open position count is reached
              </p>
            </div>
            <Switch
              checked={risk.position_limit_enabled}
              onCheckedChange={(v) => handleChange({ position_limit_enabled: v })}
            />
          </div>
          {risk.position_limit_enabled && (
            <div className="flex items-center gap-2 pl-1">
              <Label className="w-40 text-xs">Max open positions</Label>
              <Input
                type="number"
                className="w-24 h-7 text-xs"
                value={risk.max_open_positions}
                min={1}
                step={1}
                onChange={(e) => handleChange({ max_open_positions: parseInt(e.target.value) || 5 })}
              />
            </div>
          )}
        </div>

        {/* Rate Limit */}
        <div className="flex flex-col gap-3 rounded-lg border p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Rate Limit</p>
              <p className="text-xs text-muted-foreground">
                Limit entries per symbol within a rolling time window
              </p>
            </div>
            <Switch
              checked={risk.rate_limit_enabled}
              onCheckedChange={(v) => handleChange({ rate_limit_enabled: v })}
            />
          </div>
          {risk.rate_limit_enabled && (
            <div className="flex flex-col gap-2 pl-1">
              <div className="flex items-center gap-2">
                <Label className="w-40 text-xs">Max trades per symbol</Label>
                <Input
                  type="number"
                  className="w-24 h-7 text-xs"
                  value={risk.rate_limit_max_trades}
                  min={1}
                  step={1}
                  onChange={(e) =>
                    handleChange({ rate_limit_max_trades: parseInt(e.target.value) || 3 })
                  }
                />
              </div>
              <div className="flex items-center gap-2">
                <Label className="w-40 text-xs">Window (hours)</Label>
                <Input
                  type="number"
                  className="w-24 h-7 text-xs"
                  value={risk.rate_limit_window_hours}
                  min={0.5}
                  step={0.5}
                  onChange={(e) =>
                    handleChange({ rate_limit_window_hours: parseFloat(e.target.value) || 4 })
                  }
                />
              </div>
            </div>
          )}
        </div>

        {/* Hedging */}
        <div className="flex flex-col gap-3 rounded-lg border p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Hedging Allowed</p>
              <p className="text-xs text-muted-foreground">
                Allow opening opposite-side positions on the same symbol
              </p>
            </div>
            <Switch
              checked={risk.hedging_allowed}
              onCheckedChange={(v) => handleChange({ hedging_allowed: v })}
            />
          </div>
        </div>

        {saving && <p className="text-xs text-muted-foreground">Saving…</p>}
      </div>
    );
  }
  ```

- [ ] **Step 3: Ensure `useRef` is imported**

  Check that `useRef` is included in the React imports at the top of `page.tsx`. If not, add it:
  ```typescript
  import { useEffect, useRef, useState } from "react";
  ```

- [ ] **Step 4: Ensure `Switch`, `Label`, `Input` are imported**

  These are shadcn/ui primitives. Check existing imports in `page.tsx`. If any are missing, add:
  ```typescript
  import { Switch } from "@/components/ui/switch";
  import { Label } from "@/components/ui/label";
  import { Input } from "@/components/ui/input";
  ```

- [ ] **Step 5: Add RiskManagerSection to the page render**

  Find the existing section structure in `SettingsPage` (the card-based layout). Add a new card for Risk Manager. It should follow the same `<Card>` pattern as the Maintenance section. Add after the Maintenance card:

  ```tsx
  <Card>
    <CardHeader>
      <CardTitle>Risk Manager</CardTitle>
      <CardDescription>
        Configure and toggle individual risk rules. Changes are saved instantly.
      </CardDescription>
    </CardHeader>
    <CardContent>
      <RiskManagerSection />
    </CardContent>
  </Card>
  ```

- [ ] **Step 6: TypeScript compile check**

  ```bash
  cd frontend && npx tsc --noEmit 2>&1 | head -30
  ```
  Expected: No errors

- [ ] **Step 7: Dev server smoke test**

  ```bash
  cd frontend && npm run dev
  ```
  Navigate to `http://localhost:3000/settings`. Verify:
  - "Risk Manager" card is visible
  - Toggles work (each toggle shows/hides its inputs)
  - Changes persist after page refresh (fetch from backend)

- [ ] **Step 8: Commit**

  ```bash
  git add frontend/src/types/trading.ts frontend/src/lib/api/settings.ts frontend/src/app/settings/page.tsx
  git commit -m "feat(settings): add Risk Manager section with toggleable rules"
  ```

---

## Final Verification

- [ ] **Run full backend test suite**

  ```bash
  cd backend && uv run pytest -v
  ```
  Expected: All tests pass

- [ ] **Manual end-to-end check**

  1. Open Settings → Risk Manager
  2. Toggle "Rate Limit" on, set max trades = 2, window = 1 hour
  3. Refresh page — settings persist
  4. Toggle "Drawdown Check" on — verify it saves
  5. Toggle "Hedging Allowed" off — verify it saves

- [ ] **Commit summary tag**

  ```bash
  git log --oneline -6
  ```
  Expected: 6 commits visible for this feature
