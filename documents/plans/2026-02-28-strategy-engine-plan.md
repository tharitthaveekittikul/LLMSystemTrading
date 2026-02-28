# Strategy Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a named Strategy model, an APScheduler-based background scheduler, and a frontend management UI so trades run autonomously on a schedule without the frontend being open.

**Architecture:** A new strategies table holds config/prompt/code strategies. An account_strategies junction table binds accounts to strategies (many-to-many). APScheduler starts in the FastAPI lifespan and creates one job per (binding x symbol); each job calls AITradingService.analyze_and_trade() with strategy-specific overrides. Code-based strategies are Python files in backend/strategies/ inheriting BaseStrategy, loaded via importlib.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, APScheduler 3.x, Next.js 16, shadcn/ui, TypeScript.

---

## Task Overview (12 tasks)

| # | Task | Files |
|---|------|-------|
| 1 | DB models: Strategy + AccountStrategy | db/models.py |
| 2 | Add apscheduler dependency | pyproject.toml |
| 3 | BaseStrategy abstract class | strategies/base_strategy.py |
| 4 | Example code strategy | strategies/eurusd_m15_scalp.py |
| 5 | StrategyOverrides + AITradingService update | services/ai_trading.py |
| 6 | Scheduler service | services/scheduler.py |
| 7 | Strategy API routes (CRUD + binding) | api/routes/strategies.py |
| 8 | Wire scheduler + router into main.py | main.py |
| 9 | Frontend types + API client | types/trading.ts, lib/api.ts |
| 10 | Frontend strategy list page | app/strategies/page.tsx |
| 11 | Frontend create wizard | app/strategies/new/page.tsx |
| 12 | Frontend detail page | app/strategies/[id]/page.tsx |

---

## Task 1: DB models — Strategy + AccountStrategy

**Files:**
- Modify: backend/db/models.py
- Test: backend/tests/test_strategy_models.py

### Step 1: Write the failing test

Add to backend/tests/test_strategy_models.py:

    import json
    import pytest
    from db.models import Strategy, AccountStrategy, Trade

    def test_strategy_defaults():
        s = Strategy(name="Test", symbols=json.dumps(["EURUSD"]))
        assert s.strategy_type == "config"
        assert s.trigger_type == "candle_close"
        assert s.is_active is True
        assert s.news_filter is True

    def test_account_strategy_unique_constraint():
        unique_cols = [
            set(c.columns.keys())
            for c in AccountStrategy.__table__.constraints
            if hasattr(c, "columns") and len(list(c.columns)) == 2
        ]
        assert {"account_id", "strategy_id"} in unique_cols

    def test_trade_has_strategy_id_column():
        cols = {c.name for c in Trade.__table__.columns}
        assert "strategy_id" in cols

### Step 2: Run to verify it fails

    cd backend && uv run pytest tests/test_strategy_models.py -v
Expected: ImportError — Strategy class does not exist yet.

### Step 3: Add models to backend/db/models.py

Add UniqueConstraint to the SQLAlchemy import line:

    from sqlalchemy import String, Text, ForeignKey, UniqueConstraint

Add after KillSwitchLog class:

    class Strategy(Base):
        __tablename__ = "strategies"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column(String(255), unique=True)
        description: Mapped[str | None] = mapped_column(Text, nullable=True)
        strategy_type: Mapped[str] = mapped_column(String(20), default="config")
        trigger_type: Mapped[str] = mapped_column(String(20), default="candle_close")
        interval_minutes: Mapped[int | None] = mapped_column(nullable=True)
        symbols: Mapped[str] = mapped_column(Text, default="[]")
        timeframe: Mapped[str] = mapped_column(String(10), default="M15")
        lot_size: Mapped[float | None] = mapped_column(nullable=True)
        sl_pips: Mapped[float | None] = mapped_column(nullable=True)
        tp_pips: Mapped[float | None] = mapped_column(nullable=True)
        news_filter: Mapped[bool] = mapped_column(default=True)
        custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
        module_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
        class_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
        is_active: Mapped[bool] = mapped_column(default=True)
        created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
        account_bindings: Mapped[list["AccountStrategy"]] = relationship(
            "AccountStrategy", back_populates="strategy", cascade="all, delete-orphan"
        )

    class AccountStrategy(Base):
        __tablename__ = "account_strategies"
        id: Mapped[int] = mapped_column(primary_key=True)
        account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
        strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
        is_active: Mapped[bool] = mapped_column(default=True)
        created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
        __table_args__ = (UniqueConstraint("account_id", "strategy_id", name="uq_account_strategy"),)
        account: Mapped["Account"] = relationship("Account", back_populates="strategy_bindings")
        strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="account_bindings")

Add strategy_id to Trade class (after is_paper_trade):

    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id"), nullable=True)

Add strategy_id to AIJournal class (after created_at):

    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id"), nullable=True)

Add strategy_bindings to Account class (after trades relationship):

    strategy_bindings: Mapped[list["AccountStrategy"]] = relationship(
        "AccountStrategy", back_populates="account", cascade="all, delete-orphan"
    )

### Step 4: Run to verify it passes

    cd backend && uv run pytest tests/test_strategy_models.py -v
Expected: 3 tests PASS.

### Step 5: Commit

    git add backend/db/models.py backend/tests/test_strategy_models.py
    git commit -m "feat(strategy): add Strategy and AccountStrategy DB models"

---

## Task 2: Add apscheduler dependency

**Files:**
- Modify: backend/pyproject.toml

### Step 1: Add to pyproject.toml dependencies list

    "apscheduler>=3.10,<4",

### Step 2: Install and verify tables

    cd backend && uv sync
    uv run python -c "import asyncio; from db.postgres import init_db; asyncio.run(init_db()); print('Tables OK')"

Expected: Tables OK — strategies and account_strategies exist in PostgreSQL.

### Step 3: Commit

    git add backend/pyproject.toml backend/uv.lock
    git commit -m "feat(strategy): add apscheduler dependency"

---

## Task 3: BaseStrategy abstract class

**Files:**
- Create: `backend/strategies/__init__.py`
- Create: `backend/strategies/base_strategy.py`
- Test: `backend/tests/test_base_strategy.py`

### Step 1: Write the failing test

```python
# backend/tests/test_base_strategy.py
import pytest
from strategies.base_strategy import BaseStrategy
from ai.orchestrator import TradingSignal

class ConcreteStrategy(BaseStrategy):
    symbols = ["EURUSD"]
    timeframe = "M15"
    def system_prompt(self) -> str:
        return "You are a test strategy."

def test_symbols():
    assert ConcreteStrategy().symbols == ["EURUSD"]

def test_defaults():
    s = ConcreteStrategy()
    assert s.lot_size() is None and s.sl_pips() is None
    assert s.news_filter() is True
    assert s.trigger_type == "candle_close"

def test_abstract_requires_system_prompt():
    with pytest.raises(TypeError):
        BaseStrategy()

def test_should_trade_hold_returns_false():
    s = ConcreteStrategy()
    sig = TradingSignal(action="HOLD", entry=1.1, stop_loss=1.09,
                        take_profit=1.11, confidence=0.5, rationale="flat", timeframe="M15")
    assert s.should_trade(sig) is False

def test_should_trade_buy_returns_true():
    s = ConcreteStrategy()
    sig = TradingSignal(action="BUY", entry=1.1, stop_loss=1.09,
                        take_profit=1.11, confidence=0.8, rationale="bull", timeframe="M15")
    assert s.should_trade(sig) is True
```

### Step 2: Run to verify it fails

```bash
cd backend && uv run pytest tests/test_base_strategy.py -v
```
Expected: `ModuleNotFoundError`

### Step 3: Create the files

`backend/strategies/__init__.py` — empty package marker file.

`backend/strategies/base_strategy.py`:

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.orchestrator import TradingSignal

class BaseStrategy(ABC):
    """
    Abstract base for all code-based trading strategies.
    Subclass this, implement system_prompt(), set symbols/timeframe/trigger_type.
    """
    symbols: list[str] = []
    timeframe: str = "M15"
    trigger_type: str = "candle_close"   # "interval" | "candle_close"
    interval_minutes: int = 15

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the full LLM system prompt for this strategy."""
        ...

    # Risk overrides — return None to use account/system defaults
    def lot_size(self) -> float | None: return None
    def sl_pips(self) -> float | None: return None
    def tp_pips(self) -> float | None: return None
    def news_filter(self) -> bool: return True

    def should_trade(self, signal: "TradingSignal") -> bool:
        """Return False to skip execution. Signal is always logged to AIJournal."""
        return signal.action != "HOLD"
```

### Step 4: Run to verify it passes

```bash
cd backend && uv run pytest tests/test_base_strategy.py -v
```
Expected: 5 tests PASS.

### Step 5: Commit

```bash
git add backend/strategies/ backend/tests/test_base_strategy.py
git commit -m "feat(strategy): add BaseStrategy abstract class"
```

---

## Task 4: Example code-based strategy

**Files:**
- Create: `backend/strategies/eurusd_m15_scalp.py`
- Test: extend `backend/tests/test_base_strategy.py`

### Step 1: Append test

```python
def test_eurusd_scalp_is_valid_strategy():
    from strategies.eurusd_m15_scalp import EURUSDScalp
    s = EURUSDScalp()
    assert "EURUSD" in s.symbols
    assert s.timeframe == "M15"
    assert len(s.system_prompt()) > 20
    assert s.lot_size() == 0.05
    assert s.sl_pips() == 15
```

### Step 2: Run to verify it fails

```bash
cd backend && uv run pytest tests/test_base_strategy.py::test_eurusd_scalp_is_valid_strategy -v
```

### Step 3: Create backend/strategies/eurusd_m15_scalp.py

```python
from strategies.base_strategy import BaseStrategy

class EURUSDScalp(BaseStrategy):
    """M15 scalping strategy for EURUSD and GBPUSD."""
    symbols = ["EURUSD", "GBPUSD"]
    timeframe = "M15"
    trigger_type = "candle_close"

    def system_prompt(self) -> str:
        return (
            "You are a scalping specialist on the M15 timeframe.\n"
            "Focus on momentum trades during the London open session (07:00-09:00 UTC).\n"
            "Only enter when RSI divergence AND a 9/21 EMA crossover align.\n"
            "Keep stops tight: maximum 15 pips. Risk 0.5% of account per trade.\n"
            "Outside London open hours, prefer HOLD unless confidence exceeds 0.90."
        )

    def lot_size(self) -> float: return 0.05
    def sl_pips(self) -> float: return 15
```

### Step 4: Run all tests

```bash
cd backend && uv run pytest tests/test_base_strategy.py -v
```
Expected: 6 tests PASS.

### Step 5: Commit

```bash
git add backend/strategies/eurusd_m15_scalp.py backend/tests/test_base_strategy.py
git commit -m "feat(strategy): add EURUSDScalp example code-based strategy"
```

---

## Task 5: StrategyOverrides + AITradingService update

**Files:**
- Modify: `backend/services/ai_trading.py`
- Modify: `backend/ai/orchestrator.py`
- Test: extend `backend/tests/test_ai_trading.py`

### Step 1: Append failing tests

```python
def test_strategy_overrides_defaults():
    from services.ai_trading import StrategyOverrides
    o = StrategyOverrides()
    assert o.lot_size is None
    assert o.sl_pips is None
    assert o.custom_prompt is None
    assert o.strategy_id is None

def test_analyze_and_trade_has_strategy_params():
    import inspect
    from services.ai_trading import AITradingService
    sig = inspect.signature(AITradingService.analyze_and_trade)
    assert "strategy_id" in sig.parameters
    assert "strategy_overrides" in sig.parameters
```

### Step 2: Run to verify it fails

```bash
cd backend && uv run pytest tests/test_ai_trading.py::test_strategy_overrides_defaults tests/test_ai_trading.py::test_analyze_and_trade_has_strategy_params -v
```

### Step 3: Update ai_trading.py

Add this Pydantic model after imports, before the `AITradingService` class:

```python
from pydantic import BaseModel as PydanticBase

class StrategyOverrides(PydanticBase):
    """Per-strategy parameter overrides passed from the scheduler."""
    lot_size: float | None = None
    sl_pips: float | None = None
    tp_pips: float | None = None
    news_filter: bool = True
    custom_prompt: str | None = None
    strategy_id: int | None = None
```

Update `analyze_and_trade` signature:

```python
async def analyze_and_trade(
    self,
    account_id: int,
    symbol: str,
    timeframe: str,
    db: AsyncSession,
    strategy_id: int | None = None,
    strategy_overrides: StrategyOverrides | None = None,
) -> AnalysisResult:
```

Inside the method body:
1. After loading account, resolve effective lot size:
   ```python
   lot_size = (strategy_overrides.lot_size if strategy_overrides and strategy_overrides.lot_size
               else account.max_lot_size)
   ```
2. When calling `orchestrator.analyze_market()`, add:
   ```python
   system_prompt_override=strategy_overrides.custom_prompt if strategy_overrides else None,
   ```
3. When building `AIJournal(...)`, add: `strategy_id=strategy_id`
4. When building `Trade(...)`, add: `strategy_id=strategy_id`

Update `backend/ai/orchestrator.py` — add param to `analyze_market()`:

```python
async def analyze_market(
    ...,
    system_prompt_override: str | None = None,
) -> TradingSignal:
    # At the point where the system prompt string is used in ChatPromptTemplate:
    system_content = system_prompt_override if system_prompt_override else DEFAULT_SYSTEM_PROMPT
    # use system_content when building the prompt template
```

### Step 4: Run tests

```bash
cd backend && uv run pytest tests/test_ai_trading.py -v
```
Expected: all tests PASS.

### Step 5: Commit

```bash
git add backend/services/ai_trading.py backend/ai/orchestrator.py backend/tests/test_ai_trading.py
git commit -m "feat(strategy): add StrategyOverrides and wire strategy_id into AITradingService"
```

---

## Task 6: Scheduler service

**Files:**
- Create: `backend/services/scheduler.py`
- Test: `backend/tests/test_scheduler.py`

### Step 1: Write the failing test

```python
# backend/tests/test_scheduler.py
from unittest.mock import MagicMock
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from services.scheduler import _make_trigger, _job_id, CANDLE_CRON

def _mock_strategy(trigger_type, timeframe="M15", interval_minutes=15):
    s = MagicMock()
    s.trigger_type = trigger_type
    s.timeframe = timeframe
    s.interval_minutes = interval_minutes
    return s

def test_make_trigger_interval():
    assert isinstance(_make_trigger(_mock_strategy("interval", interval_minutes=30)), IntervalTrigger)

def test_make_trigger_candle_close():
    assert isinstance(_make_trigger(_mock_strategy("candle_close")), CronTrigger)

def test_make_trigger_unknown_timeframe_defaults():
    assert isinstance(_make_trigger(_mock_strategy("candle_close", timeframe="UNKNOWN")), CronTrigger)

def test_job_id_format():
    assert _job_id(42, "EURUSD") == "strat_42_EURUSD"

def test_candle_cron_covers_all_timeframes():
    for tf in ("M15", "M30", "H1", "H4", "D1"):
        assert tf in CANDLE_CRON
```

### Step 2: Run to verify it fails

```bash
cd backend && uv run pytest tests/test_scheduler.py -v
```
Expected: `ModuleNotFoundError`

### Step 3: Create backend/services/scheduler.py

```python
from __future__ import annotations
import importlib
import json
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CANDLE_CRON: dict[str, dict] = {
    "M15": dict(minute="0,15,30,45"),
    "M30": dict(minute="0,30"),
    "H1":  dict(hour="*", minute="0"),
    "H4":  dict(hour="0,4,8,12,16,20", minute="0"),
    "D1":  dict(hour="0", minute="0"),
}

_scheduler = AsyncIOScheduler()


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler


def _job_id(binding_id: int, symbol: str) -> str:
    return f"strat_{binding_id}_{symbol}"


def _make_trigger(strategy):
    if strategy.trigger_type == "interval":
        return IntervalTrigger(minutes=strategy.interval_minutes or 15)
    return CronTrigger(**CANDLE_CRON.get(strategy.timeframe, CANDLE_CRON["M15"]))


def _build_overrides(strategy):
    from services.ai_trading import StrategyOverrides
    symbols = json.loads(strategy.symbols or "[]")
    if strategy.strategy_type == "code" and strategy.module_path and strategy.class_name:
        try:
            mod = importlib.import_module(strategy.module_path)
            instance = getattr(mod, strategy.class_name)()
            return (instance.symbols or symbols), StrategyOverrides(
                lot_size=instance.lot_size(),
                sl_pips=instance.sl_pips(),
                tp_pips=instance.tp_pips(),
                news_filter=instance.news_filter(),
                custom_prompt=instance.system_prompt(),
                strategy_id=strategy.id,
            )
        except Exception:
            logger.exception("Failed to load code strategy %s.%s — using DB config",
                             strategy.module_path, strategy.class_name)
    return symbols, StrategyOverrides(
        lot_size=strategy.lot_size,
        sl_pips=strategy.sl_pips,
        tp_pips=strategy.tp_pips,
        news_filter=strategy.news_filter,
        custom_prompt=strategy.custom_prompt,
        strategy_id=strategy.id,
    )


def _add_binding_jobs(scheduler: AsyncIOScheduler, binding) -> None:
    strategy = binding.strategy
    symbols, overrides = _build_overrides(strategy)
    trigger = _make_trigger(strategy)
    for symbol in symbols:
        job_id = _job_id(binding.id, symbol)
        scheduler.add_job(
            _run_strategy_job,
            trigger=trigger,
            id=job_id,
            args=[binding.account_id, symbol, strategy.timeframe, overrides],
            replace_existing=True,
            misfire_grace_time=60,
        )
        logger.info("Scheduled %s (trigger=%s)", job_id, strategy.trigger_type)


async def _run_strategy_job(account_id: int, symbol: str, timeframe: str, overrides) -> None:
    from db.postgres import AsyncSessionLocal
    from services.ai_trading import AITradingService
    async with AsyncSessionLocal() as db:
        service = AITradingService()
        result = await service.analyze_and_trade(
            account_id=account_id, symbol=symbol, timeframe=timeframe,
            db=db, strategy_id=overrides.strategy_id, strategy_overrides=overrides,
        )
        logger.info("Job done: account=%d symbol=%s action=%s order=%s",
                    account_id, symbol, result.signal.action, result.order_placed)


async def start_scheduler(db: "AsyncSession") -> None:
    from db.models import AccountStrategy
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(AccountStrategy)
        .where(AccountStrategy.is_active.is_(True))
        .options(selectinload(AccountStrategy.strategy), selectinload(AccountStrategy.account))
    )
    bindings = [b for b in result.scalars().all()
                if b.account.is_active and b.strategy.is_active]
    for binding in bindings:
        _add_binding_jobs(_scheduler, binding)
    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))


def add_binding_jobs(binding) -> None:
    """Call from API route when a binding is activated."""
    _add_binding_jobs(_scheduler, binding)


def remove_binding_jobs(binding_id: int, symbols: list[str]) -> None:
    """Call from API route when a binding is paused or deleted."""
    for symbol in symbols:
        job_id = _job_id(binding_id, symbol)
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
            logger.info("Removed job %s", job_id)


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
```

### Step 4: Run to verify it passes

```bash
cd backend && uv run pytest tests/test_scheduler.py -v
```
Expected: 5 tests PASS.

### Step 5: Commit

```bash
git add backend/services/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat(strategy): add APScheduler-based strategy scheduler service"
```

---

## Task 7: Strategy API routes

**Files:**
- Create: `backend/api/routes/strategies.py`
- Test: `backend/tests/test_strategy_routes.py`

### Step 1: Write the failing test

```python
# backend/tests/test_strategy_routes.py
import pytest
from httpx import AsyncClient
from main import app

@pytest.mark.anyio
async def test_list_strategies_empty(db_session):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/strategies")
    assert resp.status_code == 200
    assert resp.json() == []

@pytest.mark.anyio
async def test_create_and_get_strategy(db_session):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        body = {"name": "Test M15", "strategy_type": "config",
                "trigger_type": "candle_close", "symbols": ["EURUSD"], "timeframe": "M15"}
        resp = await ac.post("/api/v1/strategies", json=body)
    assert resp.status_code == 201
    assert resp.json()["name"] == "Test M15"

@pytest.mark.anyio
async def test_duplicate_name_returns_409(db_session):
    body = {"name": "Dup", "strategy_type": "config",
            "symbols": ["EURUSD"], "timeframe": "M15", "trigger_type": "candle_close"}
    async with AsyncClient(app=app, base_url="http://test") as ac:
        await ac.post("/api/v1/strategies", json=body)
        resp = await ac.post("/api/v1/strategies", json=body)
    assert resp.status_code == 409

@pytest.mark.anyio
async def test_delete_strategy(db_session):
    body = {"name": "ToDel", "strategy_type": "config",
            "symbols": ["EURUSD"], "timeframe": "M15", "trigger_type": "candle_close"}
    async with AsyncClient(app=app, base_url="http://test") as ac:
        sid = (await ac.post("/api/v1/strategies", json=body)).json()["id"]
        resp = await ac.delete(f"/api/v1/strategies/{sid}")
    assert resp.status_code == 204
```

### Step 2: Run to verify it fails

```bash
cd backend && uv run pytest tests/test_strategy_routes.py -v
```
Expected: 404 or ImportError.

### Step 3: Create backend/api/routes/strategies.py

Key schemas (add at top of file):
```python
from pydantic import BaseModel

class StrategyCreate(BaseModel):
    name: str
    description: str | None = None
    strategy_type: str = "config"
    trigger_type: str = "candle_close"
    interval_minutes: int | None = None
    symbols: list[str] = []
    timeframe: str = "M15"
    lot_size: float | None = None
    sl_pips: float | None = None
    tp_pips: float | None = None
    news_filter: bool = True
    custom_prompt: str | None = None
    module_path: str | None = None
    class_name: str | None = None

class StrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    strategy_type: str | None = None
    trigger_type: str | None = None
    interval_minutes: int | None = None
    symbols: list[str] | None = None
    timeframe: str | None = None
    lot_size: float | None = None
    sl_pips: float | None = None
    tp_pips: float | None = None
    news_filter: bool | None = None
    custom_prompt: str | None = None
    module_path: str | None = None
    class_name: str | None = None
    is_active: bool | None = None

class StrategyResponse(BaseModel):
    id: int
    name: str
    description: str | None
    strategy_type: str
    trigger_type: str
    interval_minutes: int | None
    symbols: list[str]
    timeframe: str
    lot_size: float | None
    sl_pips: float | None
    tp_pips: float | None
    news_filter: bool
    custom_prompt: str | None
    module_path: str | None
    class_name: str | None
    is_active: bool
    binding_count: int = 0
    model_config = {"from_attributes": True}

class BindRequest(BaseModel):
    account_id: int
    is_active: bool = True

class BindingResponse(BaseModel):
    id: int
    account_id: int
    strategy_id: int
    is_active: bool
    account_name: str
    model_config = {"from_attributes": True}
```

Key routes (full implementation):

**GET /strategies** — list all with binding count
**POST /strategies** — create (409 if name exists); store symbols as JSON string
**GET /strategies/{id}** — get one (404 if missing)
**PATCH /strategies/{id}** — update fields (exclude_none=True)
**DELETE /strategies/{id}** — remove scheduler jobs, delete cascade
**POST /strategies/{id}/bind** — create AccountStrategy row; call `add_binding_jobs()` if is_active
**PATCH /strategies/{id}/bind/{account_id}** — toggle is_active; start/stop jobs
**DELETE /strategies/{id}/bind/{account_id}** — remove jobs, delete binding
**GET /strategies/{id}/runs** — last 50 AIJournal rows where `strategy_id == id`

Note: `symbols` is stored in DB as JSON string; always serialize on write with `json.dumps()` and deserialize on read with `json.loads()`.

### Step 4: Run to verify it passes

```bash
cd backend && uv run pytest tests/test_strategy_routes.py -v
```
Expected: 4 tests PASS.

### Step 5: Commit

```bash
git add backend/api/routes/strategies.py backend/tests/test_strategy_routes.py
git commit -m "feat(strategy): add strategy CRUD and binding API routes"
```

---

## Task 8: Wire scheduler + router into main.py

**Files:**
- Modify: `backend/main.py`

### Step 1: Add router import

Add with the other route imports:
```python
from api.routes.strategies import router as strategies_router
```

### Step 2: Include router

Add after the other `app.include_router(...)` calls:
```python
app.include_router(strategies_router, prefix="/api/v1/strategies", tags=["strategies"])
```

### Step 3: Add scheduler to lifespan

In the lifespan `async with` block, after `await init_db()`:
```python
from services.scheduler import start_scheduler, stop_scheduler
from db.postgres import AsyncSessionLocal
async with AsyncSessionLocal() as db:
    await start_scheduler(db)
```

In the shutdown section (after cancelling the equity_poller task):
```python
stop_scheduler()
```

### Step 4: Verify startup works

```bash
cd backend && uv run uvicorn main:app --reload --port 8000
```
Expected in logs:
- `Scheduler started with N active jobs`
- No import errors

Verify endpoint:
```bash
curl http://localhost:8000/api/v1/strategies
```
Expected: `[]`

### Step 5: Run full test suite

```bash
cd backend && uv run pytest -v
```
Expected: all tests PASS.

### Step 6: Commit

```bash
git add backend/main.py
git commit -m "feat(strategy): wire scheduler and strategies router into FastAPI lifespan"
```

---

## Task 9: Frontend — types + API client

**Files:**
- Modify: `frontend/src/types/trading.ts`
- Modify: `frontend/src/lib/api.ts`

### Step 1: Add to frontend/src/types/trading.ts

```typescript
export interface Strategy {
  id: number
  name: string
  description: string | null
  strategy_type: "config" | "prompt" | "code"
  trigger_type: "interval" | "candle_close"
  interval_minutes: number | null
  symbols: string[]
  timeframe: string
  lot_size: number | null
  sl_pips: number | null
  tp_pips: number | null
  news_filter: boolean
  custom_prompt: string | null
  module_path: string | null
  class_name: string | null
  is_active: boolean
  binding_count: number
}

export interface StrategyBinding {
  id: number
  account_id: number
  strategy_id: number
  is_active: boolean
  account_name: string
}

export interface CreateStrategyPayload {
  name: string
  description?: string
  strategy_type: "config" | "prompt" | "code"
  trigger_type: "interval" | "candle_close"
  interval_minutes?: number
  symbols: string[]
  timeframe: string
  lot_size?: number
  sl_pips?: number
  tp_pips?: number
  news_filter?: boolean
  custom_prompt?: string
  module_path?: string
  class_name?: string
}

export interface StrategyRun {
  id: number
  symbol: string
  timeframe: string
  signal: "BUY" | "SELL" | "HOLD"
  confidence: number
  rationale: string
  created_at: string
}
```

### Step 2: Add to frontend/src/lib/api.ts

Import the new types at the top where other types are imported.

Add the strategiesApi object:

```typescript
export const strategiesApi = {
  list: () => apiRequest<Strategy[]>("/strategies"),
  get: (id: number) => apiRequest<Strategy>(`/strategies/${id}`),
  create: (payload: CreateStrategyPayload) =>
    apiRequest<Strategy>("/strategies", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: number, payload: Partial<CreateStrategyPayload> & { is_active?: boolean }) =>
    apiRequest<Strategy>(`/strategies/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  delete: (id: number) =>
    apiRequest<void>(`/strategies/${id}`, { method: "DELETE" }),
  bind: (id: number, account_id: number, is_active = true) =>
    apiRequest<StrategyBinding>(`/strategies/${id}/bind`, {
      method: "POST",
      body: JSON.stringify({ account_id, is_active }),
    }),
  unbind: (id: number, account_id: number) =>
    apiRequest<void>(`/strategies/${id}/bind/${account_id}`, { method: "DELETE" }),
  toggleBinding: (id: number, account_id: number, is_active: boolean) =>
    apiRequest<StrategyBinding>(`/strategies/${id}/bind/${account_id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active }),
    }),
  runs: (id: number) => apiRequest<StrategyRun[]>(`/strategies/${id}/runs`),
}
```

### Step 3: Commit

```bash
git add frontend/src/types/trading.ts frontend/src/lib/api.ts
git commit -m "feat(strategy): add Strategy types and API client"
```

---

## Task 10: Frontend — strategy list page

**Files:**
- Create: `frontend/src/app/strategies/page.tsx`
- Modify: `frontend/src/components/app-sidebar.tsx`

### Step 1: Create frontend/src/app/strategies/page.tsx

Build a card grid with:
- Header: "Strategies" title + description + "New Strategy" button (links to `/strategies/new`)
- Empty state: dashed border box with "Create your first strategy" CTA
- Card per strategy showing: name, description, type badge, timeframe badge, trigger badge, bound accounts count, active/pause Switch, Edit button (link to `/strategies/{id}`), Delete button with confirm dialog
- `useEffect` loads from `strategiesApi.list()` on mount
- Toggle active calls `strategiesApi.update(id, { is_active: !strategy.is_active })` then updates local state
- Delete calls `strategiesApi.delete(id)` with `window.confirm` guard, then filters local state

Type badge colors:
- config: blue
- prompt: purple
- code: green

### Step 2: Add Strategies link to sidebar

In `frontend/src/components/app-sidebar.tsx`, add to the nav items array:
```typescript
{ title: "Strategies", url: "/strategies", icon: Cpu },
```
Import `Cpu` from `lucide-react`.

### Step 3: Verify visually

Navigate to `/strategies` — shows empty state. Create a strategy and verify card appears.

### Step 4: Commit

```bash
git add frontend/src/app/strategies/ frontend/src/components/app-sidebar.tsx
git commit -m "feat(strategy): add strategy list page and sidebar nav link"
```

---

## Task 11: Frontend — create wizard

**Files:**
- Create: `frontend/src/app/strategies/new/page.tsx`

### Step 1: Create the 4-step wizard page

State: `step` (0-3), `form: CreateStrategyPayload`, `selectedAccounts: number[]`, `accounts: Account[]`

**Step 0 — Basics:**
- Name input (required, disables Next if empty)
- Description textarea (optional)
- Type selector: 3 buttons (Config / Prompt / Code) with description text below

**Step 1 — Market & Schedule:**
- Symbol tag input: text input + Add button; Enter key also adds; shows chips with × remove
- Timeframe: 5 buttons (M15, M30, H1, H4, D1)
- Trigger: 2 buttons (Candle close / Fixed interval); interval shows number input in minutes

**Step 2 — Configuration (changes per type):**
- Config: 3 number inputs (Lot size, SL pips, TP pips) + Switch for news filter
- Prompt: large textarea for custom LLM system prompt (font-mono)
- Code: module path input + class name input + instructional box explaining workflow

**Step 3 — Bind Accounts:**
- Loads accounts from `accountsApi.list()` on mount
- Checkbox list: name, live/paper badge, login number
- "Create Strategy" button disabled while submitting or if name/symbols empty

On submit: `strategiesApi.create(form)` then for each selected account `strategiesApi.bind(id, accountId)`, then `router.push("/strategies")`.

Step indicator: 4 segments at top colored based on current step.

Navigation: Back/Cancel on left, Next/Create on right.

### Step 2: Verify manually

Go through the full wizard, create a config strategy and a code strategy. Both should appear on the list page.

### Step 3: Commit

```bash
git add frontend/src/app/strategies/new/
git commit -m "feat(strategy): add strategy create wizard"
```

---

## Task 12: Frontend — strategy detail page

**Files:**
- Create: `frontend/src/app/strategies/[id]/page.tsx`

### Step 1: Create the detail page

Loads: strategy (`strategiesApi.get(id)`), runs (`strategiesApi.runs(id)`), accounts (`accountsApi.list()`)
Note: bindings come from strategy's account_bindings — the backend currently returns `binding_count`. To show binding details, add a separate GET /strategies/{id}/bindings endpoint OR embed bindings in StrategyResponse. For simplicity, load bindings from a dedicated GET call — update the routes file to add:

```
GET /strategies/{id}/bindings → list[BindingResponse]
```

Implement in `strategies.py`:
```python
@router.get("/{strategy_id}/bindings", response_model=list[BindingResponse])
async def list_bindings(strategy_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(AccountStrategy)
        .where(AccountStrategy.strategy_id == strategy_id)
        .options(selectinload(AccountStrategy.account))
    )
    bindings = result.scalars().all()
    return [BindingResponse(id=b.id, account_id=b.account_id, strategy_id=b.strategy_id,
                            is_active=b.is_active, account_name=b.account.name) for b in bindings]
```

Add `bindings` to `strategiesApi` in api.ts:
```typescript
bindings: (id: number) => apiRequest<StrategyBinding[]>(`/strategies/${id}/bindings`),
```

**Page structure:**
- Back link to `/strategies`
- Title + type/timeframe/trigger badges + active Switch
- Tabs: "Accounts (N)" | "Recent Runs (N)"

**Accounts tab:**
- List of bound accounts: name, account type (live/paper), is_active Switch, Remove button
- "Add account" section below: lists unbound accounts with Bind button
- Toggle binding: calls `strategiesApi.toggleBinding()`, updates local state
- Unbind: calls `strategiesApi.unbind()`, removes from local state
- Bind: calls `strategiesApi.bind()`, adds to local state

**Recent runs tab:**
- Table rows: signal (colored BUY=green, SELL=red, HOLD=gray), symbol, timeframe badge, confidence %, rationale (truncated), timestamp
- Empty state: "No runs yet — the scheduler will log results here"

### Step 2: Verify manually

Click Edit on a strategy card. Verify both tabs show data. Toggle a binding — job should start/stop (check backend logs).

### Step 3: Run full test suite

```bash
cd backend && uv run pytest -v
```
Expected: all tests PASS.

### Step 4: Commit

```bash
git add frontend/src/app/strategies/[id]/
git commit -m "feat(strategy): add strategy detail page with accounts and runs tabs"
```

---

## Summary

| # | Task | Key files |
|---|------|-----------|
| 1 | DB models | `db/models.py` |
| 2 | apscheduler dep | `pyproject.toml` |
| 3 | BaseStrategy | `strategies/base_strategy.py` |
| 4 | Example strategy | `strategies/eurusd_m15_scalp.py` |
| 5 | StrategyOverrides | `services/ai_trading.py`, `ai/orchestrator.py` |
| 6 | Scheduler service | `services/scheduler.py` |
| 7 | Strategy routes | `api/routes/strategies.py` |
| 8 | Wire main.py | `main.py` |
| 9 | Frontend types + API | `types/trading.ts`, `lib/api.ts` |
| 10 | Strategy list page | `app/strategies/page.tsx` |
| 11 | Create wizard | `app/strategies/new/page.tsx` |
| 12 | Detail page | `app/strategies/[id]/page.tsx` |

**After all tasks: the system trades autonomously on schedule. Frontend is optional.**
